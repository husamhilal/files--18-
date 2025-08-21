"""
MCP client wrapper that spawns the SQLite MCP server and calls tools.

If MCP is unavailable, importing this module will raise, and the app will
fallback to direct SQLite data service.
"""
import asyncio
import json
import os
import sys
from typing import Any, Dict, List, Optional

from pathlib import Path

# MCP client IO over stdio
try:
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioTransport
except Exception as e:
    raise

ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "services" / "sqlite_mcp_server.py"

class MCPBankDataService:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._session: Optional[ClientSession] = None
        self._proc = None
        # Ensure env var for server
        env = os.environ.copy()
        env['SQLITE_DB_PATH'] = db_path
        # Spawn server subprocess
        self._proc = asyncio.get_event_loop().run_until_complete(self._start_server(env))
        # Create client session
        self._session = asyncio.get_event_loop().run_until_complete(self._start_session())

    async def _start_server(self, env):
        # Launch MCP server as subprocess
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(SERVER_PATH),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=None,
            env=env
        )
        self._transport = StdioTransport(proc.stdout, proc.stdin)
        return proc

    async def _start_session(self):
        session = ClientSession(self._transport)
        await session.initialize()
        return session

    async def _call(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        if not self._session:
            raise RuntimeError("MCP session not initialized")
        result = await self._session.call_tool(tool_name, arguments)
        # Tools return JSON-serializable values
        return result

    # Public methods mirror SqliteBankDataService

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        return asyncio.get_event_loop().run_until_complete(self._call("get_user", {"user_id": user_id}))

    def get_accounts(self, user_id: str) -> List[Dict[str, Any]]:
        return asyncio.get_event_loop().run_until_complete(self._call("get_accounts", {"user_id": user_id}))

    def get_account(self, user_id: str, account_id: str) -> Optional[Dict[str, Any]]:
        return asyncio.get_event_loop().run_until_complete(self._call("get_account", {"user_id": user_id, "account_id": account_id}))

    def update_account_balance(self, user_id: str, account_id: str, new_balance: float) -> bool:
        # Not exposed as a separate tool; emulate via process_payment of negative amount? Keep it simple: not supported via MCP.
        raise NotImplementedError("Direct balance update not exposed via MCP")

    def get_recent_transactions(self, user_id: str, account_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        return asyncio.get_event_loop().run_until_complete(self._call("get_recent_transactions", {"user_id": user_id, "account_id": account_id, "limit": int(limit)}))

    def add_transaction(self, user_id: str, account_id: str, amount: float, description: str,
                        merchant: Optional[str] = None, category: Optional[str] = None) -> Dict[str, Any]:
        return asyncio.get_event_loop().run_until_complete(self._call("add_transaction", {
            "user_id": user_id, "account_id": account_id, "amount": float(amount),
            "description": description, "merchant": merchant, "category": category
        }))

    def find_payee_by_name(self, user_id: str, name: str) -> Optional[Dict[str, Any]]:
        return asyncio.get_event_loop().run_until_complete(self._call("find_payee_by_name", {"user_id": user_id, "name": name}))

    def process_payment(self, user_id: str, from_account_id: str, payee_name: str, amount: float, memo: str = "Bill Payment") -> Dict[str, Any]:
        return asyncio.get_event_loop().run_until_complete(self._call("process_payment", {
            "user_id": user_id, "from_account_id": from_account_id, "payee_name": payee_name, "amount": float(amount), "memo": memo
        }))

    def __del__(self):
        try:
            if self._session:
                asyncio.get_event_loop().run_until_complete(self._session.close())
        except Exception:
            pass
        try:
            if self._proc:
                self._proc.kill()
        except Exception:
            pass