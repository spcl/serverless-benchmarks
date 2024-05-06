import base64
import concurrent.futures
import json
import os
from typing import Any, Dict, Optional  # noqa

from azure.core.exceptions import ResourceExistsError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from azure.storage.queue import QueueServiceClient, QueueClient, QueueMessage, BinaryBase64DecodePolicy, BinaryBase64EncodePolicy
from sebs.azure.cli import AzureCLI

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
    def __init__(self, fname: str, storage_account: str):
        super().__init__()
        self.name = fname
        self.storage_account = storage_account

    @staticmethod
    def typename() -> str:
        return "Azure.QueueTrigger"

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.QUEUE

    def sync_invoke(self, payload: dict) -> ExecutionResult:

        self.logging.info(f"Invoke function {self.name}")

        # Init client
        account_url = f"https://{self.storage_account}.queue.core.windows.net"
        default_credential = DefaultAzureCredential()
        queue_client = QueueClient(account_url,
                                   queue_name=self.name,
                                   credential=default_credential)

        serialized_payload = base64.b64encode(json.dumps(payload).encode('utf-8')).decode('utf-8')

        # Create queue
        self.logging.info(f"Creating queue {self.name}")

        try:
            queue_client.create_queue()
            self.logging.info("Created queue")
        except ResourceExistsError:
            self.logging.info("Queue already exists, reusing...")

        # Publish payload to queue
        queue_client.send_message(serialized_payload)
        self.logging.info(f"Sent message to queue {self.name}")

        # TODO(oana): gather metrics

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:

        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> dict:
        return {"type": "Queue", "name": self.name, "storage_account": self.storage_account}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return QueueTrigger(obj["name"], obj["storage_account"])


class StorageTrigger(Trigger):
    def __init__(self, fname: str, storage_account: str):
        super().__init__()
        self.name = fname
        self.storage_account = storage_account

    @staticmethod
    def typename() -> str:
        return "Azure.StorageTrigger"

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.STORAGE

    def sync_invoke(self, payload: dict) -> ExecutionResult:

        self.logging.info(f"Invoke function {self.name}")

        # Init client
        account_url = f"https://{self.storage_account}.blob.core.windows.net"
        default_credential = DefaultAzureCredential()
        blob_service_client = BlobServiceClient(account_url, credential=default_credential)

        # Create container
        container_name = self.name
        self.logging.info(f"Creating container {container_name}")
        try:
            blob_service_client.create_container(container_name)
            self.logging.info("Created container")
        except ResourceExistsError:
            self.logging.info("Container already exists, reusing...")

        # Prepare blob
        file_name = "payload.json"
        with open(file_name, 'w') as fp:
            json.dump(payload, fp)

        # Upload blob
        blob_client = blob_service_client.get_blob_client(container=container_name,
                                                          blob=file_name)
        with open(file=file_name, mode="rb") as payload:
            blob_client.upload_blob(payload, overwrite=True)
        self.logging.info(f"Uploaded payload to container {container_name}")

        # TODO(oana): gather metrics

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:

        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> dict:
        return {"type": "Storage", "name": self.name, "storage_account": self.storage_account}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return StorageTrigger(obj["name"], obj["storage_account"])
