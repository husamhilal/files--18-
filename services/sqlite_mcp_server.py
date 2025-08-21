"""
SQLite MCP Server exposing banking data tools over stdio.

Run manually:
  python services/sqlite_mcp_server.py

Env:
  SQLITE_DB_PATH  (defaults to ./data/banking.db)
"""
import os
import sqlite3
import time
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

# Minimal MCP server using fastmcp
try:
    from mcp.server.fastmcp import FastMCP
except ImportError as e:
    raise SystemExit("mcp package is required for MCP server. pip install mcp") from e

def _dict_factory(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}

def _set_pragmas(conn: sqlite3.Connection):
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    conn.execute("PRAGMA cache_size=-2000;")

def get_conn(db_path: str):
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = _dict_factory
    _set_pragmas(conn)
    return conn

def _retry_locked(fn, retries: int = 5, base_delay: float = 0.1):
    last = None
    for attempt in range(retries):
        try:
            return fn()
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                time.sleep(base_delay * (2 ** attempt))
                last = e
                continue
            raise
    if last:
        raise last

DB_PATH = os.environ.get('SQLITE_DB_PATH', os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'banking.db'))
server = FastMCP("sqlite-banking")

@server.tool()
def ping() -> str:
    return "pong"

@server.tool()
def get_user(user_id: str) -> Optional[Dict[str, Any]]:
    with get_conn(DB_PATH) as c:
        return c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()

@server.tool()
def get_accounts(user_id: str) -> List[Dict[str, Any]]:
    with get_conn(DB_PATH) as c:
        return c.execute("SELECT * FROM accounts WHERE user_id=?", (user_id,)).fetchall()

@server.tool()
def get_account(user_id: str, account_id: str) -> Optional[Dict[str, Any]]:
    with get_conn(DB_PATH) as c:
        return c.execute("SELECT * FROM accounts WHERE user_id=? AND account_id=?", (user_id, account_id)).fetchone()

@server.tool()
def get_recent_transactions(user_id: str, account_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    with get_conn(DB_PATH) as c:
        return c.execute(
            "SELECT * FROM transactions WHERE user_id=? AND account_id=? ORDER BY date DESC LIMIT ?",
            (user_id, account_id, limit)
        ).fetchall()

@server.tool()
def add_transaction(user_id: str, account_id: str, amount: float, description: str,
                    merchant: Optional[str] = None, category: Optional[str] = None) -> Dict[str, Any]:
    def _do():
        with get_conn(DB_PATH) as c:
            tx_id = f"T-{int(datetime.now(timezone.utc).timestamp()*1000)}"
            c.execute(
                """INSERT INTO transactions (user_id, account_id, transaction_id, date, amount, description, merchant, category)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, account_id, tx_id, datetime.now(timezone.utc).isoformat(), float(amount), description, merchant, category or 'general')
            )
            return c.execute("SELECT * FROM transactions WHERE user_id=? AND account_id=? AND transaction_id=?",
                             (user_id, account_id, tx_id)).fetchone()
    return _retry_locked(_do)

@server.tool()
def find_payee_by_name(user_id: str, name: str) -> Optional[Dict[str, Any]]:
    with get_conn(DB_PATH) as c:
        return c.execute("SELECT * FROM payees WHERE user_id=? AND name=?", (user_id, name)).fetchone()

@server.tool()
def process_payment(user_id: str, from_account_id: str, payee_name: str, amount: float, memo: str = "Bill Payment") -> Dict[str, Any]:
    def _do():
        with get_conn(DB_PATH) as c:
            acc = c.execute("SELECT * FROM accounts WHERE user_id=? AND account_id=?", (user_id, from_account_id)).fetchone()
            if not acc:
                return {'success': False, 'error': 'Account not found'}
            balance = float(acc.get('balance', 0.0))
            if balance < amount:
                return {'success': False, 'error': 'Insufficient funds'}
            new_balance = balance - amount
            c.execute("UPDATE accounts SET balance=? WHERE user_id=? AND account_id=?", (new_balance, user_id, from_account_id))
            tx_id = f"T-{int(datetime.now(timezone.utc).timestamp()*1000)}"
            c.execute(
                """INSERT INTO transactions (user_id, account_id, transaction_id, date, amount, description, merchant, category)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, from_account_id, tx_id, datetime.now(timezone.utc).isoformat(), -float(amount), memo, payee_name, 'bill-payment')
            )
            tx = c.execute("SELECT * FROM transactions WHERE user_id=? AND account_id=? AND transaction_id=?",
                           (user_id, from_account_id, tx_id)).fetchone()
            return {'success': True, 'new_balance': new_balance, 'transaction': tx}
    return _retry_locked(_do)

if __name__ == "__main__":
    # Run over stdio per MCP spec
    server.run_stdio()