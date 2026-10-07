-- SecureBank: Banking Management System (PostgreSQL)
DROP VIEW IF EXISTS v_account_summary, v_branch_summary, v_loan_summary CASCADE;
DROP TABLE IF EXISTS audit_log, loan_payments, loans, transactions, accounts, account_types, customers, branches CASCADE;
DROP FUNCTION IF EXISTS apply_transaction(INT, VARCHAR, NUMERIC, TEXT, INT), post_monthly_interest(), calc_emi(NUMERIC, NUMERIC, INT), log_account_status() CASCADE;
DROP SEQUENCE IF EXISTS account_no_seq;

CREATE SEQUENCE account_no_seq START 10000001;

CREATE TABLE branches (
    branch_id    SERIAL PRIMARY KEY,
    branch_name  VARCHAR(60) NOT NULL UNIQUE,
    ifsc_code    VARCHAR(11) NOT NULL UNIQUE CHECK (ifsc_code ~ '^[A-Z]{4}0[A-Z0-9]{6}$'),
    city         VARCHAR(40) NOT NULL
);

CREATE TABLE customers (
    customer_id  SERIAL PRIMARY KEY,
    full_name    VARCHAR(80) NOT NULL,
    email        VARCHAR(80) NOT NULL UNIQUE CHECK (email LIKE '%_@_%.__%'),
    phone        VARCHAR(10) NOT NULL UNIQUE CHECK (phone ~ '^[6-9][0-9]{9}$'),
    dob          DATE NOT NULL CHECK (dob <= DATE '2100-01-01'),
    address      TEXT,
    created_at   TIMESTAMP NOT NULL DEFAULT NOW(),
    CHECK (dob <= CURRENT_DATE - INTERVAL '18 years')          -- customers must be adults
);

CREATE TABLE account_types (
    type_id        SERIAL PRIMARY KEY,
    type_name      VARCHAR(20) NOT NULL UNIQUE,
    min_balance    NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (min_balance >= 0),
    interest_rate  NUMERIC(4,2) NOT NULL DEFAULT 0 CHECK (interest_rate BETWEEN 0 AND 15)
);

CREATE TABLE accounts (
    account_id      SERIAL PRIMARY KEY,
    account_number  VARCHAR(12) NOT NULL UNIQUE DEFAULT ('AC' || LPAD(nextval('account_no_seq')::TEXT, 8, '0')),
    customer_id     INT NOT NULL REFERENCES customers(customer_id) ON DELETE RESTRICT,
    branch_id       INT NOT NULL REFERENCES branches(branch_id),
    type_id         INT NOT NULL REFERENCES account_types(type_id),
    balance         NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (balance >= 0),
    status          VARCHAR(10) NOT NULL DEFAULT 'Active' CHECK (status IN ('Active','Frozen','Closed')),
    opened_at       TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE transactions (
    txn_id             SERIAL PRIMARY KEY,
    account_id         INT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    txn_type           VARCHAR(15) NOT NULL
        CHECK (txn_type IN ('Deposit','Withdrawal','Transfer-In','Transfer-Out','Interest','Loan Disbursal','EMI')),
    amount             NUMERIC(14,2) NOT NULL CHECK (amount > 0),
    balance_after      NUMERIC(14,2) NOT NULL CHECK (balance_after >= 0),
    related_account_id INT REFERENCES accounts(account_id),
    description        TEXT,
    txn_time           TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE loans (
    loan_id        SERIAL PRIMARY KEY,
    customer_id    INT NOT NULL REFERENCES customers(customer_id),
    account_id     INT NOT NULL REFERENCES accounts(account_id),
    loan_type      VARCHAR(15) NOT NULL CHECK (loan_type IN ('Home','Education','Personal','Vehicle')),
    principal      NUMERIC(14,2) NOT NULL CHECK (principal > 0),
    annual_rate    NUMERIC(4,2) NOT NULL CHECK (annual_rate >= 0),
    tenure_months  INT NOT NULL CHECK (tenure_months BETWEEN 1 AND 360),
    status         VARCHAR(10) NOT NULL DEFAULT 'Pending' CHECK (status IN ('Pending','Approved','Rejected','Closed')),
    applied_at     TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE loan_payments (
    payment_id  SERIAL PRIMARY KEY,
    loan_id     INT NOT NULL REFERENCES loans(loan_id) ON DELETE CASCADE,
    amount      NUMERIC(12,2) NOT NULL CHECK (amount > 0),
    paid_at     TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE audit_log (
    log_id      SERIAL PRIMARY KEY,
    account_id  INT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    old_status  VARCHAR(10),
    new_status  VARCHAR(10) NOT NULL,
    changed_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Indexes on foreign keys and frequent filters
CREATE INDEX idx_accounts_customer ON accounts(customer_id);
CREATE INDEX idx_accounts_branch   ON accounts(branch_id);
CREATE INDEX idx_accounts_type     ON accounts(type_id);
CREATE INDEX idx_txn_account       ON transactions(account_id);
CREATE INDEX idx_txn_time          ON transactions(txn_time);
CREATE INDEX idx_loans_customer    ON loans(customer_id);
CREATE INDEX idx_loans_account     ON loans(account_id);
CREATE INDEX idx_payments_loan     ON loan_payments(loan_id);
CREATE INDEX idx_audit_account     ON audit_log(account_id);

-- Stored function: the ONLY way balances change (validates, updates balance, writes the statement row)
CREATE FUNCTION apply_transaction(p_account INT, p_type VARCHAR, p_amount NUMERIC,
                                  p_desc TEXT DEFAULT NULL, p_related INT DEFAULT NULL)
RETURNS NUMERIC AS $$
DECLARE v_bal NUMERIC; v_status VARCHAR; v_min NUMERIC; v_new NUMERIC;
BEGIN
    IF p_amount IS NULL OR p_amount <= 0 THEN
        RAISE EXCEPTION 'Amount must be greater than zero.';
    END IF;
    SELECT a.balance, a.status, t.min_balance INTO v_bal, v_status, v_min
    FROM accounts a JOIN account_types t ON t.type_id = a.type_id
    WHERE a.account_id = p_account FOR UPDATE OF a;                  -- row lock
    IF NOT FOUND THEN RAISE EXCEPTION 'Account not found.'; END IF;
    IF v_status <> 'Active' THEN
        RAISE EXCEPTION 'Account is % and cannot be used for transactions.', v_status;
    END IF;
    IF p_type IN ('Withdrawal','Transfer-Out','EMI') THEN
        v_new := v_bal - p_amount;
        IF v_new < v_min THEN
            RAISE EXCEPTION 'Insufficient funds: minimum balance of Rs. % must be maintained.', v_min;
        END IF;
    ELSE
        v_new := v_bal + p_amount;
    END IF;
    UPDATE accounts SET balance = v_new WHERE account_id = p_account;
    INSERT INTO transactions (account_id, txn_type, amount, balance_after, related_account_id, description)
    VALUES (p_account, p_type, p_amount, v_new, p_related, p_desc);
    RETURN v_new;
END;
$$ LANGUAGE plpgsql;

-- EMI = P * r * (1+r)^n / ((1+r)^n - 1), r = monthly rate
CREATE FUNCTION calc_emi(p NUMERIC, annual_rate NUMERIC, months INT) RETURNS NUMERIC AS $$
    SELECT CASE WHEN annual_rate = 0 THEN ROUND(p / months, 2)
           ELSE ROUND(p * (annual_rate/1200) * POWER(1 + annual_rate/1200, months)
                        / (POWER(1 + annual_rate/1200, months) - 1), 2) END;
$$ LANGUAGE sql IMMUTABLE;

-- Credits monthly interest to every active account whose type earns interest
CREATE FUNCTION post_monthly_interest() RETURNS INT AS $$
DECLARE r RECORD; n INT := 0; v_int NUMERIC;
BEGIN
    FOR r IN SELECT a.account_id, a.balance, t.interest_rate
             FROM accounts a JOIN account_types t ON t.type_id = a.type_id
             WHERE a.status = 'Active' AND t.interest_rate > 0 LOOP
        v_int := ROUND(r.balance * r.interest_rate / 1200, 2);
        IF v_int > 0 THEN
            PERFORM apply_transaction(r.account_id, 'Interest', v_int, 'Monthly interest');
            n := n + 1;
        END IF;
    END LOOP;
    RETURN n;
END;
$$ LANGUAGE plpgsql;

-- Trigger: audit trail for account status (opened / frozen / unfrozen / closed)
CREATE FUNCTION log_account_status() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO audit_log (account_id, old_status, new_status) VALUES (NEW.account_id, NULL, NEW.status);
    ELSIF NEW.status IS DISTINCT FROM OLD.status THEN
        INSERT INTO audit_log (account_id, old_status, new_status) VALUES (NEW.account_id, OLD.status, NEW.status);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_account_status AFTER INSERT OR UPDATE OF status ON accounts
FOR EACH ROW EXECUTE FUNCTION log_account_status();

-- Views
CREATE VIEW v_account_summary AS
SELECT a.account_id, a.account_number, c.full_name, t.type_name, b.branch_name, a.balance, a.status, a.opened_at
FROM accounts a
JOIN customers c ON c.customer_id = a.customer_id
JOIN account_types t ON t.type_id = a.type_id
JOIN branches b ON b.branch_id = a.branch_id;

CREATE VIEW v_branch_summary AS
SELECT b.branch_name, b.city, COUNT(a.account_id) AS accounts, COALESCE(SUM(a.balance), 0) AS total_balance
FROM branches b LEFT JOIN accounts a ON a.branch_id = b.branch_id
GROUP BY b.branch_id;

CREATE VIEW v_loan_summary AS
SELECT l.loan_id, c.full_name, a.account_number, l.loan_type, l.principal, l.annual_rate, l.tenure_months,
       calc_emi(l.principal, l.annual_rate, l.tenure_months) AS emi, l.status,
       COUNT(p.payment_id) AS emis_paid, l.applied_at
FROM loans l
JOIN customers c ON c.customer_id = l.customer_id
JOIN accounts a ON a.account_id = l.account_id
LEFT JOIN loan_payments p ON p.loan_id = l.loan_id
GROUP BY l.loan_id, c.full_name, a.account_number;
