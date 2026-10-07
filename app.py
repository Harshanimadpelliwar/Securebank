import os
from decimal import Decimal, InvalidOperation

import psycopg2
from psycopg2 import errors
from flask import Flask, flash, redirect, render_template, request, url_for
from markupsafe import Markup

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-me")
LOAN_RATES = {"Home": 8.5, "Education": 9.0, "Personal": 12.0, "Vehicle": 9.5}


def get_conn():
    return psycopg2.connect(host=os.getenv("DB_HOST", "localhost"), port=os.getenv("DB_PORT", "5432"),
                            dbname=os.getenv("DB_NAME", "securebank"), user=os.getenv("DB_USER", "bank"),
                            password=os.getenv("DB_PASSWORD", "bank123"))


def query(sql, params=()):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


def tx(work):
    """Run work(cursor) as ONE transaction: COMMIT on success, ROLLBACK + flash message on any error."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            result = work(cur)
        conn.commit()
        return result
    except errors.UniqueViolation:
        conn.rollback(); flash("Duplicate value: this email, phone or code already exists.", "error")
    except errors.CheckViolation:
        conn.rollback(); flash("Rejected by a database CHECK constraint (for example: age below 18, invalid phone/email).", "error")
    except Exception as e:
        conn.rollback(); flash(str(e).split("\n")[0], "error")
    finally:
        conn.close()
    return None


def amount(field="amount"):
    try:
        v = Decimal(request.form[field]).quantize(Decimal("0.01"))
    except (InvalidOperation, KeyError):
        raise ValueError("Enter a valid amount.")
    if v <= 0:
        raise ValueError("Amount must be greater than zero.")
    return v


def money(x):
    return f"Rs. {x:,.2f}"


def fmt(ts):
    return ts.strftime("%Y-%m-%d %H:%M") if ts else ""


def button(url, label, cls=""):
    return Markup('<form method="post" action="{}"><button class="btn {}">{}</button></form>').format(url, cls, label)


def link(url, label):
    return Markup('<a class="btn" href="{}">{}</a>').format(url, label)


def account_options():
    return [(r[0], f"{r[1]} - {r[2]} ({r[3]}) - {money(r[4])}") for r in query(
        "SELECT account_id, account_number, full_name, type_name, balance FROM v_account_summary WHERE status='Active' ORDER BY account_id")]


def form_page(title, fields, submit, subtitle=""):
    return render_template("form.html", title=title, fields=fields, submit=submit, subtitle=subtitle)


@app.route("/")
def index():
    s = query("""SELECT (SELECT COUNT(*) FROM customers), (SELECT COUNT(*) FROM accounts WHERE status='Active'),
                        (SELECT COALESCE(SUM(balance),0) FROM accounts), (SELECT COUNT(*) FROM loans WHERE status='Approved')""")[0]
    stats = [s[0], s[1], money(s[2]), s[3]]
    rows = [[r[0], r[1], r[2], r[3], money(r[4]), money(r[5]), fmt(r[6])] for r in query(
        """SELECT t.txn_id, a.account_number, c.full_name, t.txn_type, t.amount, t.balance_after, t.txn_time
           FROM transactions t JOIN accounts a ON a.account_id = t.account_id
           JOIN customers c ON c.customer_id = a.customer_id ORDER BY t.txn_id DESC LIMIT 8""")]
    return render_template("index.html", stats=stats, rows=rows,
                           interest=button(url_for("interest"), "Post monthly interest"))


@app.route("/customers")
def customers():
    rows = [[r[0], r[1], r[2], r[3], r[4], money(r[5])] for r in query(
        """SELECT c.customer_id, c.full_name, c.email, c.phone, COUNT(a.account_id), COALESCE(SUM(a.balance),0)
           FROM customers c LEFT JOIN accounts a ON a.customer_id = c.customer_id GROUP BY c.customer_id ORDER BY 1""")]
    return render_template("page.html", title="Customers", subtitle="Registered customers with their account count and total balance",
        top=link(url_for("new_customer"), "+ Add customer"),
        sections=[(None, ["ID", "Name", "Email", "Phone", "Accounts", "Total Balance"], rows)])


@app.route("/customers/new", methods=["GET", "POST"])
def new_customer():
    if request.method == "POST":
        f = request.form
        r = tx(lambda cur: cur.execute(
            "INSERT INTO customers (full_name, email, phone, dob, address) VALUES (%s,%s,%s,%s,%s)",
            (f["full_name"].strip(), f["email"].strip(), f["phone"].strip(), f["dob"], f["address"].strip())) or True)
        if r:
            flash("Customer added successfully.", "ok")
            return redirect(url_for("customers"))
    return form_page("Add Customer", [("full_name", "Full name", "text"), ("email", "Email", "email"), ("phone", "Phone (10 digits)", "text"),
                                      ("dob", "Date of birth", "date"), ("address", "Address", "text")], "Add customer")


@app.route("/accounts")
def accounts():
    rows = []
    for r in query("SELECT * FROM v_account_summary ORDER BY account_id"):
        toggle = button(url_for("toggle_account", aid=r[0]), "Unfreeze" if r[6] == "Frozen" else "Freeze", "green" if r[6] == "Frozen" else "grey")
        rows.append([r[1], r[2], r[3], r[4], money(r[5]), r[6], link(url_for("statement", aid=r[0]), "Statement"), toggle])
    return render_template("page.html", title="Accounts", subtitle="All accounts (from view v_account_summary)",
        top=link(url_for("new_account"), "+ Open account"),
        sections=[(None, ["Account No", "Customer", "Type", "Branch", "Balance", "Status", "", ""], rows)])


@app.route("/accounts/new", methods=["GET", "POST"])
def new_account():
    if request.method == "POST":
        def work(cur):
            dep = amount("deposit")
            cur.execute("SELECT min_balance, type_name FROM account_types WHERE type_id = %s", (request.form["type_id"],))
            mn, tname = cur.fetchone()
            if dep < mn:
                raise ValueError(f"A {tname} account needs an opening deposit of at least {money(mn)}.")
            cur.execute("INSERT INTO accounts (customer_id, branch_id, type_id) VALUES (%s,%s,%s) RETURNING account_id, account_number",
                        (request.form["customer_id"], request.form["branch_id"], request.form["type_id"]))
            aid, no = cur.fetchone()
            cur.execute("SELECT apply_transaction(%s, 'Deposit', %s, 'Opening deposit')", (aid, dep))
            return no
        no = tx(work)
        if no:
            flash(f"Account {no} opened successfully.", "ok")
            return redirect(url_for("accounts"))
    return form_page("Open Account", [
        ("customer_id", "Customer", "select", query("SELECT customer_id, full_name FROM customers ORDER BY full_name")),
        ("branch_id", "Branch", "select", query("SELECT branch_id, branch_name FROM branches ORDER BY branch_id")),
        ("type_id", "Account type", "select", [(r[0], f"{r[1]} (min balance {money(r[2])}, interest {r[3]}%)") for r in
                                               query("SELECT type_id, type_name, min_balance, interest_rate FROM account_types ORDER BY type_id")]),
        ("deposit", "Opening deposit (Rs.)", "number")], "Open account")


@app.post("/accounts/<int:aid>/toggle")
def toggle_account(aid):
    tx(lambda cur: cur.execute("""UPDATE accounts SET status = CASE WHEN status = 'Active' THEN 'Frozen' ELSE 'Active' END
                                  WHERE account_id = %s AND status <> 'Closed'""", (aid,)))
    return redirect(url_for("accounts"))


@app.route("/accounts/<int:aid>")
def statement(aid):
    info = query("SELECT account_number, full_name, type_name, branch_name, balance, status FROM v_account_summary WHERE account_id = %s", (aid,))
    if not info:
        flash("Account not found.", "error")
        return redirect(url_for("accounts"))
    i = info[0]
    rows = [[r[0], fmt(r[1]), r[2], money(r[3]), money(r[4]), r[5] or ""] for r in query(
        "SELECT txn_id, txn_time, txn_type, amount, balance_after, description FROM transactions WHERE account_id = %s ORDER BY txn_id DESC", (aid,))]
    return render_template("page.html", title=f"Statement: {i[0]}", subtitle=f"{i[1]} | {i[2]} account | {i[3]} branch | Balance {money(i[4])} | {i[5]}",
        sections=[(None, ["Txn ID", "Time", "Type", "Amount", "Balance After", "Description"], rows)])


@app.route("/transact", methods=["GET", "POST"])
def transact():
    if request.method == "POST":
        def work(cur):
            cur.execute("SELECT apply_transaction(%s, %s, %s, %s)", (request.form["account_id"], request.form["txn_type"], amount(),
                                                                       request.form["description"].strip() or None))
            return cur.fetchone()[0]
        bal = tx(work)
        if bal is not None:
            flash(f"{request.form['txn_type']} successful. New balance: {money(bal)}", "ok")
            return redirect(url_for("transact"))
    return form_page("Deposit / Withdraw", [
        ("account_id", "Account", "select", account_options()), ("txn_type", "Transaction", "select", [("Deposit", "Deposit"), ("Withdrawal", "Withdrawal")]),
        ("amount", "Amount (Rs.)", "number"), ("description", "Description (optional)", "text")], "Submit",
        "Runs the stored function apply_transaction() inside one database transaction.")


@app.route("/transfer", methods=["GET", "POST"])
def transfer():
    if request.method == "POST":
        def work(cur):
            a, b, amt = int(request.form["from_id"]), int(request.form["to_id"]), amount()
            if a == b:
                raise ValueError("Source and destination accounts must be different.")
            cur.execute("SELECT account_id, account_number FROM accounts WHERE account_id IN (%s, %s) ORDER BY account_id FOR UPDATE", (a, b))
            no = dict(cur.fetchall())          # locks both rows in a fixed order (prevents deadlock)
            note = request.form["description"].strip()
            cur.execute("SELECT apply_transaction(%s, 'Transfer-Out', %s, %s, %s)", (a, amt, f"Transfer to {no[b]}. {note}".strip(), b))
            cur.execute("SELECT apply_transaction(%s, 'Transfer-In', %s, %s, %s)", (b, amt, f"Transfer from {no[a]}. {note}".strip(), a))
            return f"{money(amt)} transferred from {no[a]} to {no[b]}."
        msg = tx(work)
        if msg:
            flash(msg, "ok")
            return redirect(url_for("transfer"))
    opts = account_options()
    return form_page("Transfer Funds", [("from_id", "From account", "select", opts), ("to_id", "To account", "select", opts),
                                        ("amount", "Amount (Rs.)", "number"), ("description", "Remark (optional)", "text")], "Transfer",
                     "Debit and credit happen in one transaction: both succeed or both are rolled back.")


@app.route("/loans")
def loans():
    rows = []
    for r in query("SELECT * FROM v_loan_summary ORDER BY loan_id DESC"):
        if r[8] == "Pending":
            act = [button(url_for("loan_action", lid=r[0], act="approve"), "Approve", "green"), button(url_for("loan_action", lid=r[0], act="reject"), "Reject", "grey")]
        elif r[8] == "Approved":
            act = [button(url_for("loan_action", lid=r[0], act="pay"), "Pay EMI")]
        else:
            act = []
        rows.append([r[0], r[1], r[3], money(r[4]), f"{r[5]}%", r[6], money(r[7]), r[8], f"{r[9]}/{r[6]}", *(act + [""] * (2 - len(act)))])
    return render_template("page.html", title="Loans", subtitle="Loan applications, approval and EMI payments (EMI from stored function calc_emi)",
        top=link(url_for("new_loan"), "+ Apply for loan"),
        sections=[(None, ["ID", "Customer", "Type", "Principal", "Rate", "Months", "EMI", "Status", "EMIs Paid", "", ""], rows)])


@app.route("/loans/new", methods=["GET", "POST"])
def new_loan():
    if request.method == "POST":
        f = request.form
        def work(cur):
            amt = amount("principal")
            cur.execute("""INSERT INTO loans (customer_id, account_id, loan_type, principal, annual_rate, tenure_months)
                           SELECT customer_id, account_id, %s, %s, %s, %s FROM accounts WHERE account_id = %s AND status = 'Active'
                           RETURNING loan_id""", (f["loan_type"], amt, LOAN_RATES[f["loan_type"]], int(f["tenure"]), f["account_id"]))
            if not cur.fetchone():
                raise ValueError("The selected account is not active.")
            return True
        if tx(work):
            flash("Loan application submitted (status: Pending).", "ok")
            return redirect(url_for("loans"))
    return form_page("Apply for Loan", [("account_id", "Customer account (loan is credited here, EMI is debited from here)", "select", account_options()),
        ("loan_type", "Loan type", "select", [(k, f"{k} ({v}% p.a.)") for k, v in LOAN_RATES.items()]),
        ("principal", "Loan amount (Rs.)", "number"), ("tenure", "Tenure (months, 1-360)", "number")], "Apply")


@app.post("/loans/<int:lid>/<act>")
def loan_action(lid, act):
    def work(cur):
        cur.execute("""SELECT account_id, principal, status, calc_emi(principal, annual_rate, tenure_months), tenure_months
                       FROM loans WHERE loan_id = %s FOR UPDATE""", (lid,))
        row = cur.fetchone()
        if not row:
            raise ValueError("Loan not found.")
        acc, principal, status, emi, months = row
        if act in ("approve", "reject"):
            if status != "Pending":
                raise ValueError("Only pending loans can be approved or rejected.")
            cur.execute("UPDATE loans SET status = %s WHERE loan_id = %s", ("Approved" if act == "approve" else "Rejected", lid))
            if act == "approve":
                cur.execute("SELECT apply_transaction(%s, 'Loan Disbursal', %s, %s)", (acc, principal, f"Loan {lid} disbursed"))
                return f"Loan {lid} approved and {money(principal)} credited to the account."
            return f"Loan {lid} rejected."
        if act == "pay":
            if status != "Approved":
                raise ValueError("EMI can only be paid for approved loans.")
            cur.execute("SELECT apply_transaction(%s, 'EMI', %s, %s)", (acc, emi, f"EMI loan {lid}"))
            cur.execute("INSERT INTO loan_payments (loan_id, amount) VALUES (%s, %s)", (lid, emi))
            cur.execute("SELECT COUNT(*) FROM loan_payments WHERE loan_id = %s", (lid,))
            if cur.fetchone()[0] >= months:
                cur.execute("UPDATE loans SET status = 'Closed' WHERE loan_id = %s", (lid,))
            return f"EMI of {money(emi)} paid for loan {lid}."
        raise ValueError("Unknown action.")
    msg = tx(work)
    if msg:
        flash(msg, "ok")
    return redirect(url_for("loans"))


@app.post("/interest")
def interest():
    n = tx(lambda cur: (cur.execute("SELECT post_monthly_interest()"), cur.fetchone()[0])[1])
    if n is not None:
        flash(f"Monthly interest credited to {n} accounts.", "ok")
    return redirect(url_for("index"))


@app.route("/analytics")
def analytics():
    m = lambda rows, idx: [[*(r[:idx]), money(r[idx]), *(r[idx + 1:])] for r in rows]
    s = [
        ("Branch summary (view with LEFT JOIN + GROUP BY)", ["Branch", "City", "Accounts", "Total Balance"], m(query("SELECT * FROM v_branch_summary ORDER BY 1"), 3)),
        ("Account types (JOIN + COUNT + AVG)", ["Type", "Accounts", "Average Balance"], m(query(
            """SELECT t.type_name, COUNT(a.account_id), COALESCE(ROUND(AVG(a.balance),2),0) FROM account_types t
               LEFT JOIN accounts a ON a.type_id = t.type_id GROUP BY t.type_name ORDER BY 2 DESC"""), 2)),
        ("Top customers by total balance (SUM + GROUP BY + LIMIT)", ["Customer", "Accounts", "Total Balance"], m(query(
            """SELECT c.full_name, COUNT(*), SUM(a.balance) FROM customers c JOIN accounts a ON a.customer_id = c.customer_id
               GROUP BY c.customer_id ORDER BY 3 DESC LIMIT 5"""), 2)),
        ("Customers without any account (NOT EXISTS)", ["ID", "Customer", "Phone"], query(
            """SELECT customer_id, full_name, phone FROM customers c WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE a.customer_id = c.customer_id)""")),
        ("Transactions above the average amount (subquery)", ["Txn ID", "Account", "Type", "Amount"], [
            [r[0], r[1], r[2], money(r[3])] for r in query(
                """SELECT t.txn_id, a.account_number, t.txn_type, t.amount FROM transactions t JOIN accounts a ON a.account_id = t.account_id
                   WHERE t.amount > (SELECT AVG(amount) FROM transactions) ORDER BY t.amount DESC LIMIT 6""")]),
        ("Monthly transaction summary by type (GROUP BY + HAVING)", ["Month", "Type", "Count", "Total"], [
            [r[0], r[1], r[2], money(r[3])] for r in query(
                """SELECT to_char(txn_time, 'YYYY-MM'), txn_type, COUNT(*), SUM(amount) FROM transactions
                   GROUP BY 1, 2 HAVING COUNT(*) >= 1 ORDER BY 1 DESC, 4 DESC""")]),
        ("Loan portfolio by status", ["Status", "Loans", "Total Principal"], m(query(
            "SELECT status, COUNT(*), SUM(principal) FROM loans GROUP BY status ORDER BY 2 DESC"), 2)),
        ("Account status audit log (filled by trigger)", ["Account", "Old", "New", "Changed At"], [
            [r[0], r[1] or "-", r[2], fmt(r[3])] for r in query(
                """SELECT a.account_number, l.old_status, l.new_status, l.changed_at FROM audit_log l
                   JOIN accounts a ON a.account_id = l.account_id ORDER BY l.log_id DESC LIMIT 6""")]),
    ]
    return render_template("page.html", title="Analytics", subtitle="SQL queries: views, joins, aggregates, subqueries, NOT EXISTS, trigger audit", sections=s)


if __name__ == "__main__":
    app.run(debug=True)
