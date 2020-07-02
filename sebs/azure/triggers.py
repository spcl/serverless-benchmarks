import datetime
import logging
from typing import Any, Dict, Optional  # noqa

import requests

from sebs.azure.config import AzureResources
from sebs.faas.function import ExecutionResult, Trigger


class AzureTrigger(Trigger):
    def __init__(self, data_storage_account: Optional[AzureResources.Storage] = None):
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
        self, url: str, data_storage_account: Optional[AzureResources.Storage] = None
    ):
        super().__init__(data_storage_account)
        self.url = url

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.HTTP

    def sync_invoke(self, payload: dict) -> ExecutionResult:

        payload["connection_string"] = self.data_storage_account.connection_string
        begin = datetime.datetime.now()
        ret = requests.request(method="POST", url=self.url, json=payload)
        end = datetime.datetime.now()

        if ret.status_code != 200:
            logging.error("Invocation on URL {} failed!".format(self.url))
            logging.error("Input: {}".format(payload))
            raise RuntimeError("Failed synchronous invocation of Azure Function!")

        output = ret.json()
        result = ExecutionResult.from_times(begin, end)
        result.request_id = output["request_id"]
        # General benchmark output parsing
        result.parse_benchmark_output(output)
        return result

    def async_invoke(self, payload: dict) -> ExecutionResult:
        pass

    def serialize(self) -> dict:
        return {"type": "HTTP", "url": self.url}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return HTTPTrigger(obj["url"])
