import base64
import concurrent.futures
import datetime
import json
import time
from typing import Any, Dict, Optional  # noqa

from azure.core.exceptions import ResourceExistsError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from azure.storage.queue import QueueClient

from sebs.azure.config import AzureResources
from sebs.azure.queue import AzureQueue
from sebs.faas.function import ExecutionResult, Trigger
from sebs.faas.queue import QueueType


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
    def __init__(
        self,
        fname: str,
        url: str,
        data_storage_account: Optional[AzureResources.Storage] = None,
        result_queue: Optional[AzureQueue] = None,
        with_result_queue: Optional[bool] = False
    ):
        super().__init__(data_storage_account)
        self.name = fname
        self.url = url
        self._result_queue = result_queue
        self.with_result_queue = with_result_queue

        # Create result queue for communicating benchmark results back to the
        # client.
        if (self.with_result_queue and not self._result_queue):
            self._result_queue = AzureQueue(
                self.name,
                QueueType.RESULT,
                data_storage_account,
                self.region
            )
            self._result_queue.create_queue()

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.HTTP

    @property
    def result_queue(self) -> AzureQueue:
        assert self._result_queue
        return self._result_queue

    def sync_invoke(self, payload: dict) -> ExecutionResult:

        payload["connection_string"] = self.data_storage_account.connection_string
        return self._http_invoke(payload, self.url)

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:
        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> dict:
        return {
            "type": "HTTP",
            "name": self.name,
            "url": self.url,
            "result_queue": self._result_queue.serialize() if self._result_queue else "",
            "with_result_queue": self.with_result_queue,
        }

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return HTTPTrigger(
            obj["name"],
            obj["url"],
            AzureQueue.deserialize(obj["result_queue"]) if obj["result_queue"] != "" else None,
            obj["with_result_queue"],
        )


class QueueTrigger(Trigger):
    def __init__(
        self,
        fname: str,
        storage_account: str,
        region: str,
        queue: Optional[AzureQueue] = None,
        application_name: Optional[str] = None,
        result_queue: Optional[AzureQueue] = None,
        with_result_queue: Optional[bool] = False
    ):
        super().__init__()
        self.name = fname
        self._storage_account = storage_account
        self._region = region
        self._queue = queue
        self._result_queue = result_queue
        self.with_result_queue = with_result_queue

        if (not self._queue):
            self._queue = AzureQueue(
                self.name,
                QueueType.TRIGGER,
                self.storage_account,
                self.region
            )
            self.queue.create_queue()

        # Create result queue for communicating benchmark results back to the
        # client.
        if (self.with_result_queue and not self._result_queue):
            self._result_queue = AzureQueue(
                f"{application_name}-result",
                QueueType.RESULT,
                self.storage_account,
                self.region
            )
            self._result_queue.create_queue()

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
    def region(self) -> str:
        assert self._region
        return self._region

    @property
    def queue(self) -> AzureQueue:
        assert self._queue
        return self._queue

    @property
    def result_queue(self) -> AzureQueue:
        assert self._result_queue
        return self._result_queue

    @property
    def account_url(self) -> str:
        return f"https://{self.storage_account}.queue.core.windows.net"

    @property
    def queue_name(self) -> str:
        assert self._queue_name
        return self._queue_name

    def sync_invoke(self, payload: dict) -> ExecutionResult:

        self.logging.info(f"Invoke function {self.name}")

        # Publish payload to queue
        serialized_payload = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")
        begin = datetime.datetime.now()
        self.queue.send_message(serialized_payload)

        results = self.collect_async_results(self.result_queue)

        ret = []
        for recv_ts, result_data in results.items():
            result = ExecutionResult.from_times(begin, recv_ts)
            result.parse_benchmark_output(result_data)
            ret.append(result)

        return ret

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:

        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> dict:
        return {
            "type": "Queue",
            "name": self.name,
            "storage_account": self.storage_account,
            "region": self.region,
            "queue": self.queue.serialize(),
            "result_queue": self._result_queue.serialize() if self._result_queue else "",
            "with_result_queue": self.with_result_queue,
        }

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return QueueTrigger(
            obj["name"],
            obj["storage_account"],
            obj["region"],
            AzureQueue.deserialize(obj["queue"]),
            AzureQueue.deserialize(obj["result_queue"]) if obj["result_queue"] != "" else None,
            obj["with_result_queue"],
        )


class StorageTrigger(Trigger):
    def __init__(
        self,
        fname: str,
        storage_account: str,
        region: str,
        application_name: Optional[str] = None,
        result_queue: Optional[AzureQueue] = None,
        with_result_queue: Optional[bool] = False,
        container_name: Optional[str] = None,
    ):
        super().__init__()
        self.name = fname
        self._storage_account = storage_account
        self._region = region
        self._result_queue = result_queue
        self.with_result_queue = with_result_queue
        self._container_name = None

        if container_name:
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

        # Create result queue for communicating benchmark results back to the
        # client.
        if (self.with_result_queue and not self._result_queue):
            self._result_queue = AzureQueue(
                f"{application_name}-result",
                QueueType.RESULT,
                self.storage_account,
                self.region
            )
            self._result_queue.create_queue()

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
    def region(self) -> str:
        assert self._region
        return self._region

    @property
    def result_queue(self) -> AzureQueue:
        assert self._result_queue
        return self._result_queue

    @property
    def account_url(self) -> str:
        return f"https://{self.storage_account}.blob.core.windows.net"

    @property
    def container_name(self) -> str:
        assert self._container_name
        return self._container_name

    def sync_invoke(self, payload: dict) -> list[ExecutionResult]:

        self.logging.info(f"Invoke function {self.name}")

        # Prepare blob
        file_name = "payload.json"
        with open(file_name, "w") as fp:
            json.dump(payload, fp)

        # Init client
        default_credential = DefaultAzureCredential()
        blob_service_client = BlobServiceClient(self.account_url, credential=default_credential)

        # Upload blob
        blob_client = blob_service_client.get_blob_client(
            container=self.container_name, blob=file_name
        )
        begin = datetime.datetime.now()
        with open(file=file_name, mode="rb") as payload_data:
            blob_client.upload_blob(payload_data, overwrite=True)
        self.logging.info(f"Uploaded payload to container {self.container_name}")

        results = self.collect_async_results(self.result_queue)

        ret = []
        for recv_ts, result_data in results.items():
            result = ExecutionResult.from_times(begin, recv_ts)
            result.parse_benchmark_output(result_data)
            ret.append(result)

        return ret

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:

        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> dict:
        return {
            "type": "Storage",
            "name": self.name,
            "storage_account": self.storage_account,
            "region": self.region,
            "result_queue": self._result_queue.serialize() if self._result_queue else "",
            "with_result_queue": self.with_result_queue,
            "container_name": self.container_name,
        }

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return StorageTrigger(
            fname=obj["name"],
            storage_account=obj["storage_account"],
            region=obj["region"],
            result_queue=AzureQueue.deserialize(obj["result_queue"]) if obj["result_queue"] != "" else None,
            with_result_queue=obj["with_result_queue"],
            container_name=obj["container_name"],
        )
