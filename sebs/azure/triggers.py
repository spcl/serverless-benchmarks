import datetime
import logging
from typing import Dict, Any  # noqa

import requests

from sebs.azure.config import AzureResources
from sebs.faas.function import ExecutionResult, Trigger


class HTTPTrigger(Trigger):
    def __init__(self, url: str, data_storage_account: AzureResources.Storage):
        self.url = url
        self.data_storage_account = data_storage_account

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
        result = ExecutionResult(begin, end)
        result.request_id = output["request_id"]
        # General benchmark output parsing
        result.parse_benchmark_output(output)
        return result

    def async_invoke(self, payload: dict) -> ExecutionResult:
        pass

    def serialize(self) -> dict:
        return {"type": "HTTP", "url": self.url}

    @staticmethod
    def deserialize(obj: dict, data_storage_account: AzureResources.Storage) -> Trigger:
        return HTTPTrigger(obj["url"], data_storage_account)
