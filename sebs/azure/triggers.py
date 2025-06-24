"""Azure Function triggers for SeBS benchmarking.

This module provides Azure-specific trigger implementations for invoking
serverless functions during benchmarking. It supports HTTP triggers and
integrates with Azure storage for data handling.

The trigger classes handle function invocation, result processing, and
integration with Azure-specific services like Blob Storage.

Example:
    Basic usage for HTTP trigger:

    ```python
    from sebs.azure.triggers import HTTPTrigger

    # Create HTTP trigger with function URL
    trigger = HTTPTrigger(function_url, data_storage_account)

    # Synchronous invocation
    result = trigger.sync_invoke(payload)

    # Asynchronous invocation
    future = trigger.async_invoke(payload)
    result = future.result()
    ```
"""

import concurrent.futures
from typing import Any, Dict, Optional  # noqa

from sebs.azure.config import AzureResources
from sebs.faas.function import ExecutionResult, Trigger


class AzureTrigger(Trigger):
    """Base class for Azure Function triggers.

    This abstract base class provides common functionality for Azure Function
    triggers, including data storage account management for benchmark data
    handling.

    Attributes:
        _data_storage_account: Azure storage account for benchmark data
    """

    def __init__(self, data_storage_account: Optional[AzureResources.Storage] = None) -> None:
        """Initialize Azure trigger.

        Args:
            data_storage_account: Optional Azure storage account for data operations
        """
        super().__init__()
        self._data_storage_account = data_storage_account

    @property
    def data_storage_account(self) -> AzureResources.Storage:
        """Get the data storage account.

        Returns:
            Azure storage account for benchmark data.

        Raises:
            AssertionError: If data storage account is not set.
        """
        assert self._data_storage_account
        return self._data_storage_account

    @data_storage_account.setter
    def data_storage_account(self, data_storage_account: AzureResources.Storage) -> None:
        """Set the data storage account.

        Args:
            data_storage_account: Azure storage account to set
        """
        self._data_storage_account = data_storage_account


class HTTPTrigger(AzureTrigger):
    """HTTP trigger for Azure Functions.

    This class implements HTTP-based invocation of Azure Functions, supporting
    both synchronous and asynchronous execution patterns for benchmarking.

    Attributes:
        url: HTTP endpoint URL for the Azure Function
    """

    def __init__(
        self, url: str, data_storage_account: Optional[AzureResources.Storage] = None
    ) -> None:
        """Initialize HTTP trigger.

        Args:
            url: HTTP endpoint URL for the Azure Function
            data_storage_account: Optional Azure storage account for data operations
        """
        super().__init__(data_storage_account)
        self.url = url

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        """Get the trigger type.

        Returns:
            HTTP trigger type identifier.
        """
        return Trigger.TriggerType.HTTP

    def sync_invoke(self, payload: dict) -> ExecutionResult:
        """Synchronously invoke Azure Function via HTTP.

        Sends HTTP request to the function endpoint and waits for response.

        Args:
            payload: Dictionary payload to send to the function

        Returns:
            ExecutionResult containing response data and timing information.
        """
        return self._http_invoke(payload, self.url)

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:
        """Asynchronously invoke Azure Function via HTTP.

        Submits function invocation to a thread pool for parallel execution.

        Args:
            payload: Dictionary payload to send to the function

        Returns:
            Future object that can be used to retrieve the result.
        """
        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> dict:
        """Serialize trigger to dictionary.

        Returns:
            Dictionary containing trigger type and URL.
        """
        return {"type": "HTTP", "url": self.url}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        """Deserialize trigger from dictionary.

        Args:
            obj: Dictionary containing trigger data

        Returns:
            HTTPTrigger instance with restored configuration.
        """
        return HTTPTrigger(obj["url"])
