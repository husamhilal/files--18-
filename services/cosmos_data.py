import os
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from azure.cosmos import CosmosClient, PartitionKey, exceptions
from azure.identity import ManagedIdentityCredential

logger = logging.getLogger(__name__)

class CosmosBankDataService:
    """
    Data layer for banking info using Cosmos DB (NoSQL).
    Uses system-assigned managed identity for auth.
    Single container 'bank' partitioned by /userId, storing multiple item types.
    """
    def __init__(self, credential: ManagedIdentityCredential):
        account_uri = os.environ.get('AZURE_COSMOSDB_ACCOUNT_URI')
        db_name = os.environ.get('COSMOS_DB_NAME', 'bankingdb')
        container_name = os.environ.get('COSMOS_CONTAINER_NAME', 'bank')
        if not account_uri:
            raise ValueError("AZURE_COSMOSDB_ACCOUNT_URI not set")

        # CosmosClient supports AAD via "credential"
        self.client = CosmosClient(account_uri, credential=credential)
        self.db = self.client.create_database_if_not_exists(db_name)
        self.container = self.db.create_container_if_not_exists(
            id=container_name,
            partition_key=PartitionKey(path="/userId"),
            offer_throughput=400
        )
        self.db_name = db_name
        self.container_name = container_name
        logger.info("Cosmos DB connected")

    # Users
    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        query = "SELECT * FROM c WHERE c.userId = @uid AND c.type = 'user'"
        params = [{"name": "@uid", "value": user_id}]
        items = list(self.container.query_items(query=query, parameters=params, enable_cross_partition_query=True))
        return items[0] if items else None

    # Accounts
    def get_accounts(self, user_id: str) -> List[Dict[str, Any]]:
        query = "SELECT * FROM c WHERE c.userId = @uid AND c.type = 'account'"
        params = [{"name": "@uid", "value": user_id}]
        return list(self.container.query_items(query=query, parameters=params, enable_cross_partition_query=True))

    def get_account(self, user_id: str, account_id: str) -> Optional[Dict[str, Any]]:
        query = "SELECT * FROM c WHERE c.userId = @uid AND c.type = 'account' AND c.accountId = @aid"
        params = [{"name": "@uid", "value": user_id}, {"name": "@aid", "value": account_id}]
        items = list(self.container.query_items(query=query, parameters=params, enable_cross_partition_query=True))
        return items[0] if items else None

    def update_account_balance(self, user_id: str, account_id: str, new_balance: float) -> bool:
        acc = self.get_account(user_id, account_id)
        if not acc:
            return False
        acc['balance'] = float(new_balance)
        self.container.replace_item(item=acc, body=acc)
        return True

    # Transactions
    def get_recent_transactions(self, user_id: str, account_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        query = ("SELECT TOP @lim * FROM c WHERE c.userId = @uid AND c.type = 'transaction' "
                 "AND c.accountId = @aid ORDER BY c.date DESC")
        params = [{"name": "@uid", "value": user_id}, {"name": "@aid", "value": account_id}, {"name": "@lim", "value": limit}]
        return list(self.container.query_items(query=query, parameters=params, enable_cross_partition_query=True))

    def add_transaction(self, user_id: str, account_id: str, amount: float, description: str,
                        merchant: Optional[str] = None, category: Optional[str] = None) -> Dict[str, Any]:
        tx = {
            'id': str(uuid.uuid4()),
            'type': 'transaction',
            'userId': user_id,
            'accountId': account_id,
            'transactionId': str(uuid.uuid4()),
            'date': datetime.now(timezone.utc).isoformat(),
            'amount': float(amount),
            'description': description,
            'merchant': merchant,
            'category': category or 'general'
        }
        self.container.create_item(tx)
        return tx

    # Payees and Bills
    def get_payees(self, user_id: str) -> List[Dict[str, Any]]:
        query = "SELECT * FROM c WHERE c.userId = @uid AND c.type = 'payee'"
        params = [{"name": "@uid", "value": user_id}]
        return list(self.container.query_items(query=query, parameters=params, enable_cross_partition_query=True))

    def find_payee_by_name(self, user_id: str, name: str) -> Optional[Dict[str, Any]]:
        query = "SELECT * FROM c WHERE c.userId = @uid AND c.type = 'payee' AND c.name = @name"
        params = [{"name": "@uid", "value": user_id}, {"name": "@name", "value": name}]
        items = list(self.container.query_items(query=query, parameters=params, enable_cross_partition_query=True))
        return items[0] if items else None

    def create_payee(self, user_id: str, name: str, account_number: str, address: str = "") -> Dict[str, Any]:
        item = {
            'id': str(uuid.uuid4()),
            'type': 'payee',
            'userId': user_id,
            'payeeId': str(uuid.uuid4()),
            'name': name,
            'accountNumber': account_number,
            'address': address
        }
        self.container.create_item(item)
        return item

    def create_bill(self, user_id: str, payee_id: str, amount_due: float, due_date: str, invoice_number: str) -> Dict[str, Any]:
        item = {
            'id': str(uuid.uuid4()),
            'type': 'bill',
            'userId': user_id,
            'billId': str(uuid.uuid4()),
            'payeeId': payee_id,
            'amountDue': float(amount_due),
            'dueDate': due_date,
            'invoiceNumber': invoice_number
        }
        self.container.create_item(item)
        return item

    # Payment processing
    def process_payment(self, user_id: str, from_account_id: str, payee_name: str, amount: float, memo: str = "Bill Payment") -> Dict[str, Any]:
        account = self.get_account(user_id, from_account_id)
        if not account:
            return {'success': False, 'error': 'Account not found'}
        balance = float(account.get('balance', 0.0))
        if balance < amount:
            return {'success': False, 'error': 'Insufficient funds'}
        # Deduct and add transaction
        new_balance = balance - amount
        self.update_account_balance(user_id, from_account_id, new_balance)
        tx = self.add_transaction(user_id, from_account_id, -amount, memo, merchant=payee_name, category='bill-payment')
        return {'success': True, 'new_balance': new_balance, 'transaction': tx}