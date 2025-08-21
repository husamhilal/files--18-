"""
Seed Cosmos DB with sample banking data for user 'husamhilal'
Uses system-assigned managed identity.
Run: python scripts/seed_cosmos.py
Env:
  AZURE_COSMOSDB_ACCOUNT_URI
  COSMOS_DB_NAME (optional, default 'bankingdb')
  COSMOS_CONTAINER_NAME (optional, default 'bank')
"""
import os
from datetime import datetime, timedelta, timezone
from azure.identity import ManagedIdentityCredential
from azure.cosmos import CosmosClient, PartitionKey

def main():
    account_uri = os.environ.get('AZURE_COSMOSDB_ACCOUNT_URI')
    db_name = os.environ.get('COSMOS_DB_NAME', 'bankingdb')
    container_name = os.environ.get('COSMOS_CONTAINER_NAME', 'bank')
    user_id = os.environ.get('DEMO_USER_ID', 'husamhilal')
    if not account_uri:
        raise RuntimeError("AZURE_COSMOSDB_ACCOUNT_URI not set")

    cred = ManagedIdentityCredential()
    client = CosmosClient(account_uri, credential=cred)
    db = client.create_database_if_not_exists(db_name)
    container = db.create_container_if_not_exists(id=container_name, partition_key=PartitionKey(path="/userId"))

    # Wipe existing user data (for demo)
    items = list(container.query_items(
        query="SELECT * FROM c WHERE c.userId = @uid",
        parameters=[{"name":"@uid","value":user_id}],
        enable_cross_partition_query=True))
    for it in items:
        container.delete_item(it, partition_key=it['userId'])

    # Create user
    user = {
        'id': f"user-{user_id}",
        'type': 'user',
        'userId': user_id,
        'name': 'Husam Hilal',
        'email': 'husam@example.com',
        'createdAt': datetime.now(timezone.utc).isoformat()
    }
    container.create_item(user)

    # Accounts
    accounts = [
        {
            'id': 'acc-checking',
            'type': 'account',
            'userId': user_id,
            'accountId': 'CHK-001',
            'accountType': 'checking',
            'currency': 'USD',
            'balance': 4850.75
        },
        {
            'id': 'acc-savings',
            'type': 'account',
            'userId': user_id,
            'accountId': 'SAV-001',
            'accountType': 'savings',
            'currency': 'USD',
            'balance': 15230.00
        }
    ]
    for a in accounts:
        container.create_item(a)

    # Payees
    payees = [
        {
            'id': 'payee-acme-utils',
            'type': 'payee',
            'userId': user_id,
            'payeeId': 'P-ACME',
            'name': 'ACME Utilities',
            'accountNumber': '987654321',
            'address': '123 Energy Ave, Metropolis'
        },
        {
            'id': 'payee-city-internet',
            'type': 'payee',
            'userId': user_id,
            'payeeId': 'P-CITYNET',
            'name': 'CityNet Internet',
            'accountNumber': '555000222',
            'address': '88 Fiber St, Metropolis'
        }
    ]
    for p in payees:
        container.create_item(p)

    # Recent transactions (on checking)
    base_date = datetime.now(timezone.utc)
    txs = [
        {'amount': -120.45, 'merchant': 'ACME Utilities', 'description': 'Electricity bill', 'days': 2, 'category': 'utilities'},
        {'amount': -65.00, 'merchant': 'CityNet Internet', 'description': 'Monthly internet', 'days': 6, 'category': 'utilities'},
        {'amount': -45.23, 'merchant': 'Grocery Mart', 'description': 'Groceries', 'days': 7, 'category': 'grocery'},
        {'amount': 2500.00, 'merchant': 'Employer Inc.', 'description': 'Salary', 'days': 8, 'category': 'income'},
        {'amount': -12.99, 'merchant': 'StreamingCo', 'description': 'Entertainment', 'days': 10, 'category': 'entertainment'},
    ]
    for i, t in enumerate(txs):
        item = {
            'id': f"tx-{i}",
            'type': 'transaction',
            'userId': user_id,
            'accountId': 'CHK-001',
            'transactionId': f"T-{i}",
            'date': (base_date - timedelta(days=t['days'])).isoformat(),
            'amount': t['amount'],
            'description': t['description'],
            'merchant': t['merchant'],
            'category': t['category']
        }
        container.create_item(item)

    print("Seed complete.")

if __name__ == "__main__":
    main()