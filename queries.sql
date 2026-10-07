-- SecureBank demo queries. Run in pgAdmin Query Tool (database: securebank) or:
--   psql -U bank -d securebank -f queries.sql
-- Nothing here changes data (the transfer demo is rolled back at the end).

-- 1. All accounts (view with 3 JOINs)
SELECT account_number, full_name, type_name, branch_name, balance, status FROM v_account_summary ORDER BY account_id;

-- 2. Account statement
SELECT txn_id, txn_time, txn_type, amount, balance_after, description FROM transactions WHERE account_id = 1 ORDER BY txn_id;

-- 3. Branch summary (LEFT JOIN + GROUP BY)
SELECT * FROM v_branch_summary ORDER BY branch_name;

-- 4. Top customers by total balance (SUM + GROUP BY)
SELECT c.full_name, COUNT(*) AS accounts, SUM(a.balance) AS total_balance
FROM customers c JOIN accounts a ON a.customer_id = c.customer_id GROUP BY c.customer_id ORDER BY 3 DESC LIMIT 5;

-- 5. Customers without any account (NOT EXISTS)
SELECT customer_id, full_name FROM customers c WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE a.customer_id = c.customer_id);

-- 6. Transactions above the average amount (subquery)
SELECT txn_id, account_id, txn_type, amount FROM transactions WHERE amount > (SELECT AVG(amount) FROM transactions) ORDER BY amount DESC;

-- 7. Loan summary with EMI computed by calc_emi() (view)
SELECT loan_id, full_name, loan_type, principal, annual_rate, tenure_months, emi, status, emis_paid FROM v_loan_summary ORDER BY loan_id;

-- 8. Trigger audit log
SELECT a.account_number, l.old_status, l.new_status, l.changed_at FROM audit_log l JOIN accounts a ON a.account_id = l.account_id ORDER BY l.log_id;

-- 9. Atomic transfer demo: both rows change inside the transaction, then ROLLBACK undoes both
BEGIN;
SELECT apply_transaction(2, 'Transfer-Out', 1000, 'demo transfer', 3);
SELECT apply_transaction(3, 'Transfer-In', 1000, 'demo transfer', 2);
SELECT account_id, balance FROM accounts WHERE account_id IN (2, 3) ORDER BY 1;   -- changed
ROLLBACK;
SELECT account_id, balance FROM accounts WHERE account_id IN (2, 3) ORDER BY 1;   -- original values again

-- 10. Try these one at a time (each one raises an error on purpose):
--   SELECT apply_transaction(3, 'Withdrawal', 999999);        -- minimum balance / insufficient funds
--   SELECT apply_transaction(8, 'Deposit', 100);              -- account 8 is Frozen
--   UPDATE accounts SET balance = -1 WHERE account_id = 1;    -- CHECK constraint
