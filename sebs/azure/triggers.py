import concurrent.futures
import uuid
import time
import requests
from typing import Any, Dict, Optional  # noqa

from sebs.azure.config import AzureResources
from sebs.faas.benchmark import ExecutionResult, Trigger


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
        request_id = str(uuid.uuid4())[0:8]
        input = {
            "payload": payload,
            "request_id": request_id,
            "connection_string": self.data_storage_account.connection_string
        }

        ret = self._http_invoke(input, self.url)
        ret.request_id = request_id

        # Wait for execution to finish, then print results.
        execution_running = True
        while execution_running:
            res = requests.get(ret.output["statusQueryGetUri"]).json()
            status = res["runtimeStatus"]
            execution_running = status in ("Pending", "Running")

            # If we haven't seen the result yet, wait a second.
            if execution_running:
                time.sleep(10)
            elif status == "Failed":
                self.logging.error(f"Invocation of {self.url} failed: {res}")
                self.logging.error(f"Input: {payload}")
                ret.stats.failure = True
                return ret

        return ret

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:
        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> dict:
        return {"type": "HTTP", "url": self.url}

    @classmethod
    def deserialize(cls, obj: dict) -> Trigger:
        return HTTPTrigger(obj["url"])
