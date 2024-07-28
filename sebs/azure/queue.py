from sebs.cache import Cache
from sebs.faas.config import Resources
from sebs.faas.queue import Queue

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
        queue_type: Queue.QueueType,
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
        raise NotImplementedError()

    def send_message(self, serialized_message: str):
        self.client.send_message(serialized_message)
        self.logging.info(f"Sent message to queue {self.queue_name}")

    def receive_message(self) -> str:
        raise NotImplementedError()