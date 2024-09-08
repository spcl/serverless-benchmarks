from azure.identity import ManagedIdentityCredential
from azure.storage.queue import QueueClient

class queue:
    client = None

    def __init__(self, queue_name: str, storage_account: str):
        account_url = f"https://{storage_account}.queue.core.windows.net"
        managed_credential = ManagedIdentityCredential()
        self.client = QueueClient(account_url,
                            queue_name=queue_name,
                            credential=managed_credential)

    def send_message(self, message: str):
        self.client.send_message(message)
