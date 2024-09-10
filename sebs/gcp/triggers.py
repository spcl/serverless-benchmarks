import base64
import concurrent.futures
import datetime
import json
import os
import time
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from typing import Dict, Optional  # noqa

from google.cloud import storage as gcp_storage

from sebs.gcp.gcp import GCP
from sebs.gcp.queue import GCPQueue
from sebs.faas.function import ExecutionResult, Trigger
from sebs.faas.queue import QueueType


class LibraryTrigger(Trigger):
    def __init__(self, fname: str, deployment_client: Optional[GCP] = None):
        super().__init__()
        self.name = fname
        self._deployment_client = deployment_client

    @staticmethod
    def typename() -> str:
        return "GCP.LibraryTrigger"

    @property
    def deployment_client(self) -> GCP:
        assert self._deployment_client
        return self._deployment_client

    @deployment_client.setter
    def deployment_client(self, deployment_client: GCP):
        self._deployment_client = deployment_client

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.LIBRARY

    def sync_invoke(self, payload: dict) -> ExecutionResult:

        self.logging.info(f"Invoke function {self.name}")

        # Verify that the function is deployed
        deployed = False
        while not deployed:
            if self.deployment_client.is_deployed(self.name):
                deployed = True
            else:
                time.sleep(5)

        # GCP's fixed style for a function name
        config = self.deployment_client.config
        full_func_name = (
            f"projects/{config.project_name}/locations/" f"{config.region}/functions/{self.name}"
        )
        function_client = self.deployment_client.get_function_client()
        req = (
            function_client.projects()
            .locations()
            .functions()
            .call(name=full_func_name, body={"data": json.dumps(payload)})
        )
        begin = datetime.datetime.now()
        res = req.execute()
        end = datetime.datetime.now()

        gcp_result = ExecutionResult.from_times(begin, end)
        gcp_result.request_id = res["executionId"]
        if "error" in res.keys() and res["error"] != "":
            self.logging.error("Invocation of {} failed!".format(self.name))
            self.logging.error("Input: {}".format(payload))
            gcp_result.stats.failure = True
            return gcp_result

        output = json.loads(res["result"])
        gcp_result.parse_benchmark_output(output)
        return gcp_result

    def async_invoke(self, payload: dict):
        raise NotImplementedError()

    def serialize(self) -> dict:
        return {"type": "Library", "name": self.name}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return LibraryTrigger(obj["name"])


class HTTPTrigger(Trigger):
    def __init__(self, url: str):
        super().__init__()
        self.url = url

    @staticmethod
    def typename() -> str:
        return "GCP.HTTPTrigger"

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.HTTP

    def sync_invoke(self, payload: dict) -> ExecutionResult:

        self.logging.debug(f"Invoke function {self.url}")
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
    def __init__(
        self,
        fname: str,
        queue_name: str,
        region: str,
        result_queue: Optional[GCPQueue] = None
    ):
        super().__init__()
        self.name = fname
        self._queue_name = queue_name
        self._region = region
        self._result_queue = result_queue

        # Create result queue for communicating benchmark results back to the
        # client.
        if (not self._result_queue):
            self._result_queue = GCPQueue(
                fname,
                QueueType.RESULT,
                self.region
            )
            self._result_queue.create_queue()

    @staticmethod
    def typename() -> str:
        return "GCP.QueueTrigger"

    @property
    def queue_name(self) -> str:
        assert self._queue_name
        return self._queue_name

    @property
    def region(self) -> str:
        assert self._region
        return self._region

    @property
    def result_queue(self) -> GCPQueue:
        assert self._result_queue
        return self._result_queue

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.QUEUE

    def sync_invoke(self, payload: dict) -> ExecutionResult:

        self.logging.info(f"Invoke function {self.name}")

        # Init client
        pub_sub = build("pubsub", "v1", cache_discovery=False)

        # Prepare payload
        # GCP is very particular with data encoding...
        serialized_payload = base64.b64encode(json.dumps(payload).encode("utf-8"))

        # Publish payload to queue
        begin = datetime.datetime.now()
        pub_sub.projects().topics().publish(
            topic=self.queue_name,
            body={
                "messages": [{"data": serialized_payload.decode("utf-8")}],
            },
        ).execute()

        response = ""
        while (response == ""):
            response = self.result_queue.receive_message()

        end = datetime.datetime.now()

        result = ExecutionResult.from_times(begin, end)
        result.parse_benchmark_output(json.loads(response))
        return result

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:

        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> dict:
        return {
            "type": "Queue",
            "name": self.name,
            "queue_name": self.queue_name,
            "region": self.region,
            "result_queue": self.result_queue.serialize()
        }

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return QueueTrigger(
            obj["name"],
            obj["queue_name"],
            obj["region"],
            GCPQueue.deserialize(obj["result_queue"])
        )


class StorageTrigger(Trigger):
    def __init__(
        self,
        fname: str,
        bucket_name: str,
        region: str,
        result_queue: Optional[GCPQueue] = None
    ):
        super().__init__()
        self.name = fname
        self._bucket_name = bucket_name
        self._region = region
        self._result_queue = result_queue

        # Create result queue for communicating benchmark results back to the
        # client.
        if (not self._result_queue):
            self._result_queue = GCPQueue(
                fname,
                QueueType.RESULT,
                self.region
            )
            self._result_queue.create_queue()

    @staticmethod
    def typename() -> str:
        return "GCP.StorageTrigger"

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.STORAGE

    @property
    def bucket_name(self) -> str:
        assert self._bucket_name
        return self._bucket_name

    @property
    def region(self) -> str:
        assert self._region
        return self._region

    @property
    def result_queue(self) -> GCPQueue:
        assert self._result_queue
        return self._result_queue

    def sync_invoke(self, payload: dict) -> ExecutionResult:

        self.logging.info(f"Invoke function {self.name}")

        # Init clients
        client = gcp_storage.Client()
        bucket_instance = client.bucket(self.name)

        # Prepare payload
        file_name = "payload.json"
        with open(file_name, "w") as fp:
            json.dump(payload, fp)

        # Upload object
        gcp_storage.blob._MAX_MULTIPART_SIZE = 5 * 1024 * 1024
        blob = bucket_instance.blob(blob_name=file_name, chunk_size=4 * 1024 * 1024)
        begin = datetime.datetime.now()
        blob.upload_from_filename(file_name)

        self.logging.info(f"Uploaded payload to bucket {self.bucket_name}")

        response = ""
        while (response == ""):
            response = self.result_queue.receive_message()

        end = datetime.datetime.now()

        result = ExecutionResult.from_times(begin, end)
        result.parse_benchmark_output(json.loads(response))
        return result

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:

        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> dict:
        return {
            "type": "Storage",
            "name": self.name,
            "bucket_name": self.bucket_name,
            "region": self.region,
            "result_queue": self.result_queue.serialize()
        }

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return StorageTrigger(
            obj["name"],
            obj["bucket_name"],
            obj["region"],
            GCPQueue.deserialize(obj["result_queue"])
        )
