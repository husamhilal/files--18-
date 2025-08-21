"""
Seed SQLite with sample banking data for user 'husamhilal'
Run: python scripts/seed_sqlite.py
Env:
  SQLITE_DB_PATH (optional; defaults to ./data/banking.db)
"""
import os
import sqlite3
from datetime import datetime, timedelta, timezone

DB_PATH = os.environ.get('SQLITE_DB_PATH', os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'banking.db'))

def main():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Enable WAL & concurrency-friendly settings on the DB
    c.execute("PRAGMA journal_mode=WAL;")
    c.execute("PRAGMA synchronous=NORMAL;")
    c.execute("PRAGMA busy_timeout=5000;")

    # Drop tables (demo reset)
    c.executescript("""
    DROP TABLE IF EXISTS users;
    DROP TABLE IF EXISTS accounts;
    DROP TABLE IF EXISTS transactions;
    DROP TABLE IF EXISTS payees;
    DROP TABLE IF EXISTS bills;
    """)

    # Create schema
    c.executescript("""
    CREATE TABLE users (
      id TEXT PRIMARY KEY,
      name TEXT,
      email TEXT,
      created_at TEXT
    );
    CREATE TABLE accounts (
      id TEXT PRIMARY KEY,
      user_id TEXT,
      account_id TEXT UNIQUE,
      account_type TEXT,
      currency TEXT,
      balance REAL
    );
    CREATE TABLE transactions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id TEXT,
      account_id TEXT,
      transaction_id TEXT,
      date TEXT,
      amount REAL,
      description TEXT,
      merchant TEXT,
      category TEXT
    );
    CREATE TABLE payees (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id TEXT,
      payee_id TEXT,
      name TEXT,
      account_number TEXT,
      address TEXT
    );
    CREATE TABLE bills (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id TEXT,
      bill_id TEXT,
      payee_id TEXT,
      amount_due REAL,
      due_date TEXT,
      invoice_number TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_tx_user_account_date ON transactions(user_id, account_id, date DESC);
    """)

    user_id = 'husamhilal'
    # Insert user
    c.execute("INSERT INTO users (id, name, email, created_at) VALUES (?,?,?,?)",
              (user_id, 'Husam Hilal', 'husam@example.com', datetime.now(timezone.utc).isoformat()))

    # Accounts
    accounts = [
        ('acc-checking', user_id, 'CHK-001', 'checking', 'USD', 4850.75),
        ('acc-savings',  user_id, 'SAV-001', 'savings',  'USD', 15230.00),
    ]
    c.executemany("INSERT INTO accounts (id, user_id, account_id, account_type, currency, balance) VALUES (?,?,?,?,?,?)", accounts)

    # Payees
    payees = [
        (user_id, 'P-ACME', 'ACME Utilities', '987654321', '123 Energy Ave, Metropolis'),
        (user_id, 'P-CITYNET', 'CityNet Internet', '555000222', '88 Fiber St, Metropolis'),
    ]
    c.executemany("INSERT INTO payees (user_id, payee_id, name, account_number, address) VALUES (?,?,?,?,?)", payees)

    # Transactions
    base = datetime.now(timezone.utc)
    txs = [
        (user_id, 'CHK-001', 'T-1', (base - timedelta(days=2)).isoformat(), -120.45, 'Electricity bill', 'ACME Utilities', 'utilities'),
        (user_id, 'CHK-001', 'T-2', (base - timedelta(days=6)).isoformat(), -65.00, 'Monthly internet', 'CityNet Internet', 'utilities'),
        (user_id, 'CHK-001', 'T-3', (base - timedelta(days=7)).isoformat(), -45.23, 'Groceries', 'Grocery Mart', 'grocery'),
        (user_id, 'CHK-001', 'T-4', (base - timedelta(days=8)).isoformat(), 2500.00, 'Salary', 'Employer Inc.', 'income'),
        (user_id, 'CHK-001', 'T-5', (base - timedelta(days=10)).isoformat(), -12.99, 'Entertainment', 'StreamingCo', 'entertainment'),
    ]
    c.executemany("""INSERT INTO transactions 
        (user_id, account_id, transaction_id, date, amount, description, merchant, category)
        VALUES (?,?,?,?,?,?,?,?)""", txs)

    conn.commit()
    conn.close()
    print(f"Seeded SQLite at {DB_PATH} (WAL mode enabled)")

if __name__ == '__main__':
    main()