import concurrent.futures
from typing import Any, Dict, Optional  # noqa

from sebs.azure.config import AzureResources
from sebs.faas.function import ExecutionResult, Trigger


class AzureTrigger(Trigger):
    """
    Base class for Azure triggers.

    Stores the data storage account information, which might be needed by
    some trigger types or the functions they invoke.
    """
    def __init__(self, data_storage_account: Optional[AzureResources.Storage] = None):
        """
        Initialize an AzureTrigger.

        :param data_storage_account: Optional Azure Storage account for benchmark data.
        """
        super().__init__()
        self._data_storage_account = data_storage_account

    @property
    def data_storage_account(self) -> AzureResources.Storage:
        """The Azure Storage account associated with benchmark data."""
        assert self._data_storage_account
        return self._data_storage_account

    @data_storage_account.setter
    def data_storage_account(self, data_storage_account: AzureResources.Storage):
        """Set the Azure Storage account for benchmark data."""
        self._data_storage_account = data_storage_account


class HTTPTrigger(AzureTrigger):
    """
    Represents an HTTP trigger for an Azure Function, invoked via a URL.
    """
    def __init__(self, url: str, data_storage_account: Optional[AzureResources.Storage] = None):
        """
        Initialize an HTTPTrigger.

        :param url: The invocation URL for the HTTP-triggered function.
        :param data_storage_account: Optional Azure Storage account for benchmark data.
        """
        super().__init__(data_storage_account)
        self.url = url

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        """Return the type of this trigger (HTTP)."""
        return Trigger.TriggerType.HTTP

    def sync_invoke(self, payload: dict) -> ExecutionResult:
        """
        Synchronously invoke the Azure Function via its HTTP endpoint.

        :param payload: Input payload for the function (will be sent as JSON).
        :return: ExecutionResult object containing invocation details and metrics.
        """
        return self._http_invoke(payload, self.url)

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:
        """
        Asynchronously invoke the Azure Function via its HTTP endpoint.

        Uses a ThreadPoolExecutor to perform the HTTP request in a separate thread.

        :param payload: Input payload for the function.
        :return: A Future object representing the asynchronous invocation.
        """
        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> dict:
        """
        Serialize the HTTPTrigger to a dictionary.

        :return: Dictionary representation of the trigger, including type and URL.
        """
        return {"type": "HTTP", "url": self.url}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        """
        Deserialize an HTTPTrigger from a dictionary.

        :param obj: Dictionary representation of the trigger, must contain 'url'.
        :return: A new HTTPTrigger instance.
        """
        return HTTPTrigger(obj["url"])
