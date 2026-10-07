"""One-command database setup for SecureBank (run from the VS Code terminal).
Creates user 'bank' and database 'securebank' if missing, then loads securebank.sql and sample_data.sql.
Usage: python setup_db.py   (asks for the password of the PostgreSQL superuser 'postgres')
Optional env vars: DB_HOST, DB_PORT, SUPERUSER, SUPERUSER_PASSWORD."""
import getpass, os, sys
import psycopg2

HOST, PORT = os.getenv("DB_HOST", "localhost"), os.getenv("DB_PORT", "5432")
SUPER = os.getenv("SUPERUSER", "postgres")
APP_USER, APP_PASS, APP_DB = "bank", "bank123", "securebank"
HERE = os.path.dirname(os.path.abspath(__file__))


def run_file(cur, name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        cur.execute(f.read())
    print(f"  loaded {name}")


def main():
    pw = os.getenv("SUPERUSER_PASSWORD") or getpass.getpass(f"Password for PostgreSQL user '{SUPER}': ")
    try:
        admin = psycopg2.connect(host=HOST, port=PORT, dbname="postgres", user=SUPER, password=pw)
    except psycopg2.OperationalError as e:
        sys.exit(f"\nCould not connect to PostgreSQL: {e}\nCheck that PostgreSQL is running and the password/port are correct.")
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_USER,))
        if not cur.fetchone():
            cur.execute(f"CREATE USER {APP_USER} WITH PASSWORD %s", (APP_PASS,)); print(f"Created user '{APP_USER}'")
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (APP_DB,))
        if not cur.fetchone():
            cur.execute(f"CREATE DATABASE {APP_DB} OWNER {APP_USER}"); print(f"Created database '{APP_DB}'")
        else:
            print(f"Database '{APP_DB}' already exists (it will be reset)")
    admin.close()
    conn = psycopg2.connect(host=HOST, port=PORT, dbname=APP_DB, user=APP_USER, password=APP_PASS)
    with conn, conn.cursor() as cur:
        run_file(cur, "securebank.sql"); run_file(cur, "sample_data.sql")
        cur.execute("SELECT (SELECT COUNT(*) FROM customers), (SELECT COUNT(*) FROM accounts), (SELECT COUNT(*) FROM transactions)")
        c, a, t = cur.fetchone()
    conn.close()
    print(f"\nDone. customers={c}, accounts={a}, transactions={t}")
    print("Next: python app.py   then open http://127.0.0.1:5000")


if __name__ == "__main__":
    main()
