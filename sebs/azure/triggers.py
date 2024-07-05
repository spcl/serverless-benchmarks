import base64
import concurrent.futures
import json
from typing import Any, Dict, Optional  # noqa

from azure.core.exceptions import ResourceExistsError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from azure.storage.queue import QueueClient

from sebs.azure.config import AzureResources
from sebs.faas.function import ExecutionResult, Trigger


class AzureTrigger(Trigger):
    def __init__(self, data_storage_account: Optional[AzureResources.Storage] = None):
        super().__init__()
        self._data_storage_account = data_storage_account

    @property
    def data_storage_account(self) -> AzureResources.Storage:
        assert self._data_storage_account
        return self._data_storage_account

    @data_storage_account.setter
    def data_storage_account(self, data_storage_account: AzureResources.Storage):
        self._data_storage_account = data_storage_account


class HTTPTrigger(AzureTrigger):
    def __init__(self, url: str, data_storage_account: Optional[AzureResources.Storage] = None):
        super().__init__(data_storage_account)
        self.url = url

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.HTTP

    def sync_invoke(self, payload: dict) -> ExecutionResult:

        payload["connection_string"] = self.data_storage_account.connection_string
        return self._http_invoke(payload, self.url)

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:
        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> dict:
        return {"type": "HTTP", "url": self.url}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return HTTPTrigger(obj["url"])


class QueueTrigger(Trigger):
    def __init__(self, fname: str, storage_account: str, queue_name: Optional[str] = None):
        super().__init__()
        self.name = fname
        self._storage_account = storage_account
        self._queue_name = None        

        if (queue_name):
            self._queue_name = queue_name
        else:
            # Having a queue name field is currently a bit contrived - it is mostly a
            # device to indicate that a trigger resource exists and is cached. In the
            # future, we may adopt a different convention for naming trigger resources,
            # at which point this will become truly useful.
            self._queue_name = self.name
    
            # Init client
            default_credential = DefaultAzureCredential()
            queue_client = QueueClient(self.account_url,
                                    queue_name=self.queue_name,
                                    credential=default_credential)

            # Create queue
            self.logging.info(f"Creating queue {self.queue_name}")

            try:
                queue_client.create_queue()
                self.logging.info("Created queue")
            except ResourceExistsError:
                self.logging.info("Queue already exists, reusing...")

    @staticmethod
    def typename() -> str:
        return "Azure.QueueTrigger"

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.QUEUE

    @property
    def storage_account(self) -> str:
        assert self._storage_account
        return self._storage_account
    
    @property
    def account_url(self) -> str:
        return f"https://{self.storage_account}.queue.core.windows.net"

    @property
    def queue_name(self) -> str:
        assert self._queue_name
        return self._queue_name

    def sync_invoke(self, payload: dict) -> ExecutionResult:

        self.logging.info(f"Invoke function {self.name}")

        # Prepare queue client
        default_credential = DefaultAzureCredential()
        queue_client = QueueClient(self.account_url,
                                   queue_name=self.queue_name,
                                   credential=default_credential)

        # Publish payload to queue
        serialized_payload = base64.b64encode(json.dumps(payload).encode('utf-8')).decode('utf-8')
        queue_client.send_message(serialized_payload)
        self.logging.info(f"Sent message to queue {self.queue_name}")

        # TODO(oana): gather metrics

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:

        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> dict:
        return {"type": "Queue", "name": self.name, "storage_account": self.storage_account, "queue_name": self.queue_name}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return QueueTrigger(obj["name"], obj["storage_account"], obj["queue_name"])


class StorageTrigger(Trigger):
    def __init__(self, fname: str, storage_account: str, container_name: Optional[str] = None):
        super().__init__()
        self.name = fname
        self._storage_account = storage_account

        if (container_name):
            self._container_name = container_name
        else:
            # Having a container name field is currently a bit contrived - it is mostly
            # a device to indicate that a trigger resource exists and is cached. In the
            # future, we may adopt a different convention for naming trigger resources,
            # at which point this will become truly useful.
            self._container_name = self.name

            # Init client
            default_credential = DefaultAzureCredential()
            blob_service_client = BlobServiceClient(self.account_url, credential=default_credential)

            # Create container
            self.logging.info(f"Creating container {self.container_name}")
            try:
                blob_service_client.create_container(self.container_name)
                self.logging.info("Created container")
            except ResourceExistsError:
                self.logging.info("Container already exists, reusing...")

    @staticmethod
    def typename() -> str:
        return "Azure.StorageTrigger"

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.STORAGE

    @property
    def storage_account(self) -> str:
        assert self._storage_account
        return self._storage_account

    @property
    def account_url(self) -> str:
        return f"https://{self.storage_account}.blob.core.windows.net"

    @property
    def container_name(self) -> str:
        assert self._container_name
        return self._container_name

    def sync_invoke(self, payload: dict) -> ExecutionResult:

        self.logging.info(f"Invoke function {self.name}")

        # Prepare blob
        file_name = "payload.json"
        with open(file_name, 'w') as fp:
            json.dump(payload, fp)

        # Init client
        default_credential = DefaultAzureCredential()
        blob_service_client = BlobServiceClient(self.account_url, credential=default_credential)

        # Upload blob
        blob_client = blob_service_client.get_blob_client(container=self.container_name,
                                                          blob=file_name)
        with open(file=file_name, mode="rb") as payload:
            blob_client.upload_blob(payload, overwrite=True)
        self.logging.info(f"Uploaded payload to container {self.container_name}")

        # TODO(oana): gather metrics

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:

        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> dict:
        return {"type": "Storage", "name": self.name, "storage_account": self.storage_account, "container_name": self.container_name}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return StorageTrigger(obj["name"], obj["storage_account"], obj["container_name"])
