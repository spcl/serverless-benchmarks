import os

from azure.identity import ManagedIdentityCredential
from azure.storage.queue import QueueClient, BinaryBase64DecodePolicy, BinaryBase64EncodePolicy

class queue:
    client = None

    def __init__(self, queue_name: str):
        storage_account = os.getenv('ACCOUNT_ID')
        account_url = f"https://{storage_account}.queue.core.windows.net"
        managed_credential = ManagedIdentityCredential()
        self.client = QueueClient(account_url,
                            queue_name=queue_name,
                            credential=managed_credential,
                            message_encode_policy=BinaryBase64EncodePolicy(),
                            message_decode_policy=BinaryBase64DecodePolicy())

    def send_message(self, message: str):
        self.client.send_message(message.encode('utf-8'))
