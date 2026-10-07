"""Integration tests against the real PostgreSQL database (they reload schema + sample data)."""
import os
import sys
import unittest
from decimal import Decimal as D

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as bank

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def reload_db():
    conn = bank.get_conn()
    with conn.cursor() as cur:
        for f in ("securebank.sql", "sample_data.sql"):
            with open(os.path.join(ROOT, f), encoding="utf-8") as fh:
                cur.execute(fh.read())
    conn.commit()
    conn.close()


def bal(acc):
    return bank.query("SELECT balance FROM accounts WHERE account_id=%s", (acc,))[0][0]


def ntx():
    return bank.query("SELECT COUNT(*) FROM transactions")[0][0]


class TestBank(unittest.TestCase):
    def setUp(self):
        reload_db()
        self.c = bank.app.test_client()

    def txn(self, acc, kind, amt):
        return self.c.post("/transact", data={"account_id": acc, "txn_type": kind, "amount": amt, "description": ""})

    def test_pages_load(self):
        for url in ("/", "/customers", "/accounts", "/accounts/1", "/transact", "/transfer", "/loans", "/loans/new",
                    "/customers/new", "/accounts/new", "/analytics"):
            self.assertEqual(self.c.get(url).status_code, 200, url)

    def test_sample_data_balances(self):
        self.assertEqual(bal(1), D("140676.30"))   # 50000-5000-3000+120000-2 EMIs of 10661.85
        self.assertEqual(bal(3), D("31000.00"))

    def test_deposit_and_withdraw(self):
        self.txn(3, "Deposit", "500")
        self.assertEqual(bal(3), D("31500.00"))
        self.txn(3, "Withdrawal", "1500")
        self.assertEqual(bal(3), D("30000.00"))

    def test_insufficient_funds_rolls_back(self):
        before = ntx()
        self.txn(3, "Withdrawal", "999999")
        self.assertEqual(bal(3), D("31000.00"))
        self.assertEqual(ntx(), before)

    def test_minimum_balance_enforced(self):
        self.txn(3, "Withdrawal", "30500")        # would leave 500 < 1000
        self.assertEqual(bal(3), D("31000.00"))
        self.txn(3, "Withdrawal", "30000")        # leaves exactly 1000
        self.assertEqual(bal(3), D("1000.00"))

    def test_transfer_success_and_atomic_rollback(self):
        self.c.post("/transfer", data={"from_id": 2, "to_id": 3, "amount": "1000", "description": ""})
        self.assertEqual((bal(2), bal(3)), (D("134000.00"), D("32000.00")))
        before = ntx()
        self.c.post("/transfer", data={"from_id": 3, "to_id": 8, "amount": "500", "description": ""})   # account 8 is Frozen
        self.assertEqual(bal(3), D("32000.00"))   # debit rolled back together with the failed credit
        self.assertEqual(ntx(), before)

    def test_frozen_account_and_audit_trigger(self):
        self.c.post("/accounts/7/toggle")
        self.assertEqual(bank.query("SELECT status FROM accounts WHERE account_id=7")[0][0], "Frozen")
        self.assertEqual(bank.query("SELECT old_status, new_status FROM audit_log WHERE account_id=7 ORDER BY log_id DESC")[0], ("Active", "Frozen"))
        self.txn(7, "Deposit", "100")
        self.assertEqual(bal(7), D("25000.00"))

    def test_loan_approve_and_emi(self):
        self.c.post("/loans/2/approve")
        self.assertEqual(bal(4), D("360000.00"))
        self.c.post("/loans/2/pay")
        self.assertEqual(bank.query("SELECT COUNT(*) FROM loan_payments WHERE loan_id=2")[0][0], 1)
        self.assertEqual(bank.query("SELECT txn_type FROM transactions WHERE account_id=4 ORDER BY txn_id DESC LIMIT 1")[0][0], "EMI")

    def test_emi_function(self):
        self.assertEqual(bank.query("SELECT calc_emi(120000, 12, 12)")[0][0], D("10661.85"))
        self.assertEqual(bank.query("SELECT calc_emi(12000, 0, 12)")[0][0], D("1000.00"))

    def test_monthly_interest(self):
        n = bank.tx(lambda cur: (cur.execute("SELECT post_monthly_interest()"), cur.fetchone()[0])[1])
        self.assertEqual(n, 5)   # 5 active interest-bearing accounts (Savings/Salary, not frozen)
        self.assertEqual(bank.query("SELECT COUNT(*) FROM transactions WHERE txn_type='Interest'")[0][0], 5)

    def test_constraints(self):
        self.c.post("/customers/new", data={"full_name": "Minor", "email": "m@example.com", "phone": "9000000000", "dob": "2015-01-01", "address": ""})
        self.assertEqual(bank.query("SELECT COUNT(*) FROM customers WHERE full_name='Minor'")[0][0], 0)
        import psycopg2
        conn = bank.get_conn()
        with self.assertRaises(psycopg2.errors.CheckViolation):
            with conn.cursor() as cur:
                cur.execute("UPDATE accounts SET balance = -5 WHERE account_id = 1")
        conn.rollback()
        conn.close()


if __name__ == "__main__":
    unittest.main()
