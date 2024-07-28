from googleapiclient.discovery import build

from sebs.cache import Cache
from sebs.faas.config import Resources
from sebs.faas.queue import Queue

from google.cloud import storage as gcp_storage
from googleapiclient.errors import HttpError


class GCPQueue(Queue):
    @staticmethod
    def typename() -> str:
        return "GCP.Queue"

    @staticmethod
    def deployment_name():
        return "gcp"

    def __init__(
        self,
        benchmark: str,
        queue_type: Queue.QueueType,
        cache_client: Cache,
        resources: Resources,
        region: str
    ):
        super().__init__(benchmark, queue_type, region, cache_client, resources)
        self.client = build("pubsub", "v1", cache_discovery=False)

    def create_queue(self):
        self.logging.info(f"Creating queue '{self.name}'")

        try:
            self.client.projects().topics().create(name=self.name).execute()
            self.logging.info("Created queue")
        except HttpError as http_error:
            if http_error.resp.status == 409:
                self.logging.info("Queue already exists, reusing...")

    def remove_queue(self):
        raise NotImplementedError()

    def send_message(self, serialized_message: str):
        self.client.projects().topics().publish(
                topic=self.name,
                body={
                    "messages": [{
                        "data": serialized_message.decode("utf-8")
                    }],
                }
            ).execute()

    def receive_message(self) -> str:
        raise NotImplementedError()