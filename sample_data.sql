-- Sample data for SecureBank (hypothetical customers)
INSERT INTO branches (branch_name, ifsc_code, city) VALUES
 ('Nagpur Main','SECB0000001','Nagpur'),('Wardha Road','SECB0000002','Nagpur'),('Civil Lines','SECB0000003','Nagpur');
INSERT INTO account_types (type_name, min_balance, interest_rate) VALUES
 ('Savings',1000,3.50),('Current',5000,0),('Salary',0,3.00);
INSERT INTO customers (full_name, email, phone, dob, address) VALUES
 ('Aarav Sharma','aarav.sharma@example.com','9876500001','2001-04-12','Dharampeth, Nagpur'),
 ('Riya Patil','riya.patil@example.com','9876500002','2002-08-23','Sadar, Nagpur'),
 ('Aditya Kulkarni','aditya.k@example.com','9876500003','1998-01-30','Manish Nagar, Nagpur'),
 ('Sneha Joshi','sneha.joshi@example.com','9876500004','2000-11-05','Sitabuldi, Nagpur'),
 ('Kabir Deshmukh','kabir.d@example.com','9876500005','1995-06-17','Civil Lines, Nagpur'),
 ('Ananya More','ananya.more@example.com','9876500006','2003-02-14','Wardha Road, Nagpur'),
 ('Rahul Pawar','rahul.pawar@example.com','9876500007','1999-09-09','Besa, Nagpur'),
 ('Meera Shah','meera.shah@example.com','9876500008','1997-12-01','Laxmi Nagar, Nagpur');
INSERT INTO accounts (customer_id, branch_id, type_id) VALUES
 (1,1,1),(1,1,2),(2,2,1),(3,1,3),(4,3,1),(5,2,2),(6,1,1),(7,3,1);

SELECT apply_transaction(1,'Deposit',50000,'Opening deposit'), apply_transaction(2,'Deposit',120000,'Opening deposit'),
       apply_transaction(3,'Deposit',30000,'Opening deposit'), apply_transaction(4,'Deposit',45000,'Salary credit'),
       apply_transaction(5,'Deposit',22000,'Opening deposit'), apply_transaction(6,'Deposit',250000,'Opening deposit'),
       apply_transaction(7,'Deposit',18000,'Opening deposit'), apply_transaction(8,'Deposit',9500,'Opening deposit');
SELECT apply_transaction(1,'Withdrawal',5000,'ATM withdrawal'), apply_transaction(3,'Withdrawal',2000,'ATM withdrawal'),
       apply_transaction(4,'Deposit',15000,'Bonus'), apply_transaction(5,'Withdrawal',1000,'ATM withdrawal'),
       apply_transaction(7,'Deposit',7000,'Cash deposit'), apply_transaction(2,'Withdrawal',10000,'Cheque payment');
SELECT apply_transaction(1,'Transfer-Out',3000,'Transfer to AC10000003',3), apply_transaction(3,'Transfer-In',3000,'Transfer from AC10000001',1),
       apply_transaction(6,'Transfer-Out',25000,'Transfer to AC10000002',2), apply_transaction(2,'Transfer-In',25000,'Transfer from AC10000006',6);

INSERT INTO loans (customer_id, account_id, loan_type, principal, annual_rate, tenure_months) VALUES
 (1,1,'Personal',120000,12.00,12),(3,4,'Education',300000,9.00,60),(5,5,'Vehicle',500000,9.50,48);
UPDATE loans SET status = 'Approved' WHERE loan_id = 1;
SELECT apply_transaction(1,'Loan Disbursal',120000,'Loan 1 disbursed');
SELECT apply_transaction(1,'EMI',calc_emi(120000,12,12),'EMI loan 1');
INSERT INTO loan_payments (loan_id, amount) VALUES (1, calc_emi(120000,12,12));
SELECT apply_transaction(1,'EMI',calc_emi(120000,12,12),'EMI loan 1');
INSERT INTO loan_payments (loan_id, amount) VALUES (1, calc_emi(120000,12,12));
UPDATE loans SET status = 'Rejected' WHERE loan_id = 3;
UPDATE accounts SET status = 'Frozen' WHERE account_id = 8;
