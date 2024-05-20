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
from sebs.faas.function import ExecutionResult, Trigger


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
    def __init__(self, fname: str, deployment_client: Optional[GCP] = None):
        super().__init__()
        self.name = fname
        self._deployment_client = deployment_client

    @staticmethod
    def typename() -> str:
        return "GCP.QueueTrigger"

    @property
    def deployment_client(self) -> GCP:
        assert self._deployment_client
        return self._deployment_client

    @deployment_client.setter
    def deployment_client(self, deployment_client: GCP):
        self._deployment_client = deployment_client

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.QUEUE

    def sync_invoke(self, payload: dict) -> ExecutionResult:

        self.logging.info(f"Invoke function {self.name}")

        # Init client
        pub_sub = build("pubsub", "v1", cache_discovery=False)

        # Prep
        # GCP is very particular with data encoding...
        serialized_payload = base64.b64encode(json.dumps(payload).encode("utf-8"))

        # Publish payload to queue
        pub_sub.projects().topics().publish(
                topic=self.deployment_client.get_trigger_resource_name(self.name),
                body={
                    "messages": [{
                        "data": serialized_payload.decode("utf-8")
                    }],
                }
            ).execute()

        # TODO(oana): gather metrics

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:

        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> dict:
        return {"type": "Queue", "name": self.name}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return QueueTrigger(obj["name"])


class StorageTrigger(Trigger):
    def __init__(self, fname: str):
        super().__init__()
        self.name = fname

    @staticmethod
    def typename() -> str:
        return "GCP.StorageTrigger"

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.STORAGE

    def sync_invoke(self, payload: dict) -> ExecutionResult:

        self.logging.info(f"Invoke function {self.name}")

        # Init clients
        bucket_name = self.name
        client = gcp_storage.Client();
        bucket_instance = client.bucket(bucket_name)

        # Prep
        file_name = "payload.json"
        with open(file_name, "w") as fp:
            json.dump(payload, fp)

        # Upload object
        gcp_storage.blob._MAX_MULTIPART_SIZE = 5 * 1024 * 1024
        blob = bucket_instance.blob(blob_name=file_name, chunk_size=4 * 1024 * 1024)
        blob.upload_from_filename(file_name)

        self.logging.info(f"Uploaded payload to bucket {bucket_name}")

        # TODO(oana): gather metrics

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:

        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> dict:
        return {"type": "Storage", "name": self.name}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return StorageTrigger(obj["name"])
