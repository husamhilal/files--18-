import logging
import html
from datetime import datetime
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

class AgentsOrchestrator:
    """
    Orchestrates multi-agent behavior over banking data layer (MCP over SQLite or direct SQLite).
    Produces HTML tables for balances and recent transactions for better readability.
    """
    def __init__(self, chat_service, data_service, doc_service):
        self.chat = chat_service
        self.data = data_service
        self.doc = doc_service
        self.az_agents_available = False  # reserved for future azure-ai-agents integration

    async def handle_chat(self, user_id: str, message: str, document_data: Optional[Dict] = None) -> Dict[str, Any]:
        low = message.lower()
        try:
            if any(k in low for k in ["balance", "account balance", "how much do i have"]):
                return await self._handle_balance(user_id, message)
            if any(k in low for k in ["transactions", "recent transactions", "history", "statement"]):
                return await self._handle_transactions(user_id, message)
            if any(k in low for k in ["pay", "payment", "pay bill", "bill payment", "settle", "confirm payment"]):
                return await self._handle_payment(user_id, message, document_data)

            # Default: general chat with optional document context
            resp = await self.chat.respond_with_context(message, document_data=document_data)
            # General LLM text, render as text
            resp['content_type'] = 'text'
            return resp
        except Exception as e:
            logger.error(f"Orchestrator error: {e}")
            return {'success': False, 'error': str(e), 'timestamp': datetime.utcnow().isoformat()}

    # ---------- HTML helpers ----------
    def _esc(self, v) -> str:
        return html.escape("" if v is None else str(v), quote=True)

    def _render_accounts_table(self, accounts: List[Dict[str, Any]]) -> str:
        rows = []
        for a in accounts:
            acc_type = self._esc(a.get('account_type', ''))
            acc_id = self._esc(a.get('account_id', ''))
            curr = self._esc(a.get('currency', 'USD'))
            bal = float(a.get('balance', 0.0))
            bal_str = f"{curr} {bal:,.2f}"
            bal_cls = "text-danger" if bal < 0 else "text-success"
            rows.append(f"<tr><td>{acc_type}</td><td>{acc_id}</td><td class='{bal_cls}'>{self._esc(bal_str)}</td></tr>")
        table = (
            "<div class='table-responsive'>"
            "<table class='table table-sm table-striped table-hover align-middle chat-table'>"
            "<thead><tr><th>Account</th><th>Account ID</th><th>Balance</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>"
        )
        return table

    def _render_transactions_table(self, account_id: str, txs: List[Dict[str, Any]]) -> str:
        rows = []
        for t in txs:
            date = self._esc(t.get('date', ''))
            merch = self._esc(t.get('merchant', ''))
            desc = self._esc(t.get('description', ''))
            amt = float(t.get('amount', 0.0))
            amt_cls = "text-danger" if amt < 0 else "text-success"
            sign = "-" if amt < 0 else "+"
            amt_str = f"{sign}${abs(amt):,.2f}"
            rows.append(f"<tr><td>{date}</td><td>{merch}</td><td>{desc}</td><td class='{amt_cls} text-end'>{self._esc(amt_str)}</td></tr>")
        table = (
            f"<div class='mb-2 small text-muted'>Recent transactions for account {self._esc(account_id)}:</div>"
            "<div class='table-responsive'>"
            "<table class='table table-sm table-striped table-hover align-middle chat-table'>"
            "<thead><tr><th style='min-width: 140px;'>Date</th><th style='min-width: 160px;'>Merchant</th><th>Description</th><th class='text-end' style='min-width: 120px;'>Amount</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>"
        )
        return table

    # ---------- Intents ----------
    async def _handle_balance(self, user_id: str, user_message: str) -> Dict[str, Any]:
        accounts = self.data.get_accounts(user_id)
        if not accounts:
            text = "I couldn't find any accounts for you."
            return {'success': True, 'message': text, 'timestamp': datetime.utcnow().isoformat(), 'meta': {}, 'content_type': 'text'}
        html_table = self._render_accounts_table(accounts)
        return {
            'success': True,
            'message': html_table,
            'timestamp': datetime.utcnow().isoformat(),
            'meta': {'intent': 'balance'},
            'content_type': 'html'
        }

    async def _handle_transactions(self, user_id: str, user_message: str) -> Dict[str, Any]:
        accounts = self.data.get_accounts(user_id)
        if not accounts:
            return {'success': True, 'message': "No accounts found.", 'timestamp': datetime.utcnow().isoformat(), 'meta': {}, 'content_type': 'text'}
        checking = next((a for a in accounts if str(a.get('account_type','')).lower() == 'checking'), accounts[0])
        acct_id = checking.get('account_id')
        txs = self.data.get_recent_transactions(user_id, acct_id, limit=10)
        if not txs:
            return {
                'success': True,
                'message': f"No recent transactions for account {acct_id}.",
                'timestamp': datetime.utcnow().isoformat(),
                'meta': {'accountId': acct_id},
                'content_type': 'text'
            }
        html_table = self._render_transactions_table(acct_id, txs)
        return {
            'success': True,
            'message': html_table,
            'timestamp': datetime.utcnow().isoformat(),
            'meta': {'intent': 'transactions', 'accountId': acct_id},
            'content_type': 'html'
        }

    async def _handle_payment(self, user_id: str, user_message: str, document_data: Optional[Dict]) -> Dict[str, Any]:
        payee_name = None
        amount = None

        if document_data:
            names = document_data.get('banking_info', {}).get('names', [])
            amounts = document_data.get('banking_info', {}).get('amounts', [])
            if names:
                payee_name = names[0]
            if amounts:
                for a in amounts:
                    normalized = a.replace('$', '').replace('USD', '').replace(',', '').strip()
                    try:
                        amount_val = float(normalized)
                        if amount_val > 0:
                            amount = amount_val
                            break
                    except Exception:
                        continue

        if amount is None:
            import re
            m = re.search(r'(\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})?)', user_message)
            if m:
                normalized = m.group(1).replace('$', '').replace(',', '')
                try:
                    amount = float(normalized)
                except Exception:
                    amount = None

        if payee_name is None:
            tokens = user_message.split()
            if 'to' in [t.lower() for t in tokens]:
                try:
                    idx = [t.lower() for t in tokens].index('to')
                    payee_name = " ".join(tokens[idx+1:]) if idx+1 < len(tokens) else None
                except Exception:
                    pass

        if not payee_name or not amount:
            msg = "To pay a bill, I need the payee name and the amount. You can upload the bill or tell me, e.g., 'Pay $125.50 to ACME Utilities'."
            return {'success': True, 'message': msg, 'timestamp': datetime.utcnow().isoformat(), 'meta': {'intent': 'payment', 'needs': {'payee': not bool(payee_name), 'amount': not bool(amount)}}, 'content_type': 'text'}

        accounts = self.data.get_accounts(user_id)
        if not accounts:
            return {'success': True, 'message': "No accounts found to pay from.", 'timestamp': datetime.utcnow().isoformat(), 'meta': {'intent': 'payment'}, 'content_type': 'text'}
        checking = next((a for a in accounts if str(a.get('account_type','')).lower() == 'checking'), accounts[0])
        balance = float(checking.get('balance', 0.0))
        if balance < amount:
            return {'success': True, 'message': f"Your balance (${balance:,.2f}) is insufficient to pay ${amount:,.2f}.", 'timestamp': datetime.utcnow().isoformat(), 'meta': {'intent': 'payment', 'can_pay': False}, 'content_type': 'text'}

        msg = (f"You're about to pay ${amount:,.2f} to {self._esc(payee_name)} from account {self._esc(checking.get('account_id'))} "
               f"(current balance ${balance:,.2f}). Confirm? Reply 'confirm payment' to proceed.")
        return {'success': True, 'message': msg, 'timestamp': datetime.utcnow().isoformat(), 'meta': {'intent': 'payment', 'awaiting_confirmation': True, 'amount': amount, 'payee': payee_name, 'from_account_id': checking.get('account_id')}, 'content_type': 'text'}

    async def process_confirmed_payment(self, user_id: str, amount: float, payee_name: str, from_account_id: str) -> Dict[str, Any]:
        res = self.data.process_payment(user_id, from_account_id, payee_name, amount)
        if not res.get('success'):
            return {'success': True, 'message': f"Payment failed: {res.get('error')}", 'timestamp': datetime.utcnow().isoformat(), 'meta': {'intent': 'payment'}, 'content_type': 'text'}
        new_bal = res.get('new_balance')
        tx = res.get('transaction', {})
        # Small HTML receipt
        receipt = (
            "<div class='mb-2'><strong>Payment completed</strong></div>"
            "<div class='table-responsive'>"
            "<table class='table table-sm table-bordered align-middle chat-table'>"
            "<tbody>"
            f"<tr><th>Payee</th><td>{self._esc(payee_name)}</td></tr>"
            f"<tr><th>Amount</th><td>${amount:,.2f}</td></tr>"
            f"<tr><th>From Account</th><td>{self._esc(from_account_id)}</td></tr>"
            f"<tr><th>Transaction ID</th><td>{self._esc(tx.get('transaction_id',''))}</td></tr>"
            f"<tr><th>New Balance</th><td>${new_bal:,.2f}</td></tr>"
            "</tbody></table></div>"
        )
        return {'success': True, 'message': receipt, 'timestamp': datetime.utcnow().isoformat(), 'meta': {'intent': 'payment', 'transactionId': tx.get('transaction_id')}, 'content_type': 'html'}

    async def postprocess_followup(self, user_id: str, message: str, last_meta: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        low = message.lower().strip()
        if last_meta and last_meta.get('intent') == 'payment' and last_meta.get('awaiting_confirmation'):
            if "confirm" in low:
                amount = last_meta.get('amount')
                payee = last_meta.get('payee')
                from_account_id = last_meta.get('from_account_id')
                return await self.process_confirmed_payment(user_id, amount, payee, from_account_id)
        return None