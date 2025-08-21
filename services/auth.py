import logging
from azure.identity import ManagedIdentityCredential

logger = logging.getLogger(__name__)

def get_managed_identity_credential():
    cred = ManagedIdentityCredential()
    # Validate access by requesting a token for Azure Resource Manager scope
    _ = cred.get_token("https://management.azure.com/.default")
    logger.info("System-assigned Managed Identity token retrieval succeeded")
    return cred