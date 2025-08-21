import sqlite3
import time
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

def _dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

def _set_pragmas(conn: sqlite3.Connection):
    # Improve concurrency and reduce lock contention
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")  # wait up to 5s if locked
    conn.execute("PRAGMA temp_store=MEMORY;")
    # optional cache tuning
    conn.execute("PRAGMA cache_size=-2000;")

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

class SqliteBankDataService:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _conn(self):
        # timeout here is for acquiring locks; also set busy_timeout pragma above
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = _dict_factory
        _set_pragmas(conn)
        return conn

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            r = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            return r

    def get_accounts(self, user_id: str) -> List[Dict[str, Any]]:
        with self._conn() as c:
            return c.execute("SELECT * FROM accounts WHERE user_id=?", (user_id,)).fetchall()

    def get_account(self, user_id: str, account_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            return c.execute("SELECT * FROM accounts WHERE user_id=? AND account_id=?", (user_id, account_id)).fetchone()

    def update_account_balance(self, user_id: str, account_id: str, new_balance: float) -> bool:
        def _do():
            with self._conn() as c:
                cur = c.execute("UPDATE accounts SET balance=? WHERE user_id=? AND account_id=?", (float(new_balance), user_id, account_id))
                return cur.rowcount > 0
        return _retry_locked(_do)

    def get_recent_transactions(self, user_id: str, account_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM transactions WHERE user_id=? AND account_id=? ORDER BY date DESC LIMIT ?",
                (user_id, account_id, limit)
            ).fetchall()

    def add_transaction(self, user_id: str, account_id: str, amount: float, description: str,
                        merchant: Optional[str] = None, category: Optional[str] = None) -> Dict[str, Any]:
        def _do():
            with self._conn() as c:
                tx_id = f"T-{int(datetime.now(timezone.utc).timestamp()*1000)}"
                c.execute(
                    """INSERT INTO transactions (user_id, account_id, transaction_id, date, amount, description, merchant, category)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (user_id, account_id, tx_id, datetime.now(timezone.utc).isoformat(), float(amount), description, merchant, category or 'general')
                )
                return c.execute("SELECT * FROM transactions WHERE user_id=? AND account_id=? AND transaction_id=?",
                                 (user_id, account_id, tx_id)).fetchone()
        return _retry_locked(_do)

    def find_payee_by_name(self, user_id: str, name: str) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            return c.execute("SELECT * FROM payees WHERE user_id=? AND name=?", (user_id, name)).fetchone()

    def create_payee(self, user_id: str, name: str, account_number: str, address: str = "") -> Dict[str, Any]:
        def _do():
            with self._conn() as c:
                payee_id = f"P-{int(datetime.now(timezone.utc).timestamp()*1000)}"
                c.execute(
                    "INSERT INTO payees (user_id, payee_id, name, account_number, address) VALUES (?,?,?,?,?)",
                    (user_id, payee_id, name, account_number, address)
                )
                return c.execute("SELECT * FROM payees WHERE user_id=? AND payee_id=?", (user_id, payee_id)).fetchone()
        return _retry_locked(_do)

    def process_payment(self, user_id: str, from_account_id: str, payee_name: str, amount: float, memo: str = "Bill Payment") -> Dict[str, Any]:
        def _do():
            with self._conn() as c:
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