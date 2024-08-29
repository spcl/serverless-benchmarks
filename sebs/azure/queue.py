from sebs.cache import Cache
from sebs.faas.config import Resources
from sebs.faas.queue import Queue, QueueType

from azure.core.exceptions import ResourceExistsError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from azure.storage.queue import QueueClient


class AzureQueue(Queue):
    @staticmethod
    def typename() -> str:
        return "Azure.Queue"

    @staticmethod
    def deployment_name():
        return "azure"

    @property
    def storage_account(self) -> str:
        assert self._storage_account
        return self._storage_account
    
    @property
    def account_url(self) -> str:
        return f"https://{self.storage_account}.queue.core.windows.net"

    def __init__(
        self,
        benchmark: str,
        queue_type: QueueType,
        cache_client: Cache,
        resources: Resources,
        region: str,
        storage_account: str,
    ):
        default_credential = DefaultAzureCredential()

        super().__init__(benchmark, queue_type, region, cache_client, resources)
        self._storage_account = storage_account
        self.client = QueueClient(self.account_url,
                                  queue_name=self.name,
                                  credential=default_credential)

    def create_queue(self):
        self.logging.info(f"Creating queue {self.name}")

        try:
            self.client.create_queue()
            self.logging.info("Created queue")
        except ResourceExistsError:
            self.logging.info("Queue already exists, reusing...")

    def remove_queue(self):
        self.logging.info(f"Deleting queue {self.name}")

        self.client.delete_queue()

        self.logging.info("Deleted queue")

    def send_message(self, serialized_message: str):
        self.client.send_message(serialized_message)
        self.logging.info(f"Sent message to queue {self.queue_name}")

    def receive_message(self) -> str:
        self.logging.info(f"Pulling a message from {self.name}")

        response = self.client.receive_messages(
            max_messages=1,
            timeout=5,
        )

        if (len(response) == 0):
            self.logging.info("No messages to be received")
            return

        return response[0].content