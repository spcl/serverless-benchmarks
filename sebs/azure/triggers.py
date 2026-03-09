"""Azure Function triggers for SeBS benchmarking.

This module provides Azure-specific trigger implementations for invoking
serverless functions.

Example:
    Basic usage for HTTP trigger:

    ::

        from sebs.azure.triggers import HTTPTrigger

        # Create HTTP trigger with function URL
        trigger = HTTPTrigger(function_url, data_storage_account)

        # Synchronous invocation
        result = trigger.sync_invoke(payload)

        # Asynchronous invocation
        future = trigger.async_invoke(payload)
        result = future.result()
"""

import concurrent.futures
import json
import uuid
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, Optional  # noqa
import time

from sebs.azure.config import AzureResources
from sebs.faas.function import ExecutionResult, Trigger


class AzureTrigger(Trigger):
    """Base class for Azure Function triggers.

    This abstract base class provides common functionality for Azure Function
    triggers, including data storage account management for benchmark data
    handling.

    FIXME: do we still need to know the data storage account?

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

    def _azure_http_invoke(self, payload: dict, url: str, verify_ssl: bool = True) -> ExecutionResult:
        import pycurl

        c = pycurl.Curl()
        c.setopt(pycurl.HTTPHEADER, ["Content-Type: application/json"])
        c.setopt(pycurl.POST, 1)
        c.setopt(pycurl.URL, url)
        if not verify_ssl:
            c.setopt(pycurl.SSL_VERIFYHOST, 0)
            c.setopt(pycurl.SSL_VERIFYPEER, 0)
        data = BytesIO()
        c.setopt(pycurl.WRITEFUNCTION, data.write)

        c.setopt(pycurl.POSTFIELDS, json.dumps(payload))

        begin = datetime.now()
        c.perform()
        end = datetime.now()

        status_code = c.getinfo(pycurl.RESPONSE_CODE)
        conn_time = c.getinfo(pycurl.PRETRANSFER_TIME)
        receive_time = c.getinfo(pycurl.STARTTRANSFER_TIME)

        try:
            output = json.loads(data.getvalue())

            response: Dict[str, Any] = {}
            if "statusQueryGetUri" in output:

                # Azure-specific status query logic
                statusQuery = output["statusQueryGetUri"]
                self.logging.debug(f"Azure status query: {statusQuery}")
                myQuery = pycurl.Curl()
                myQuery.setopt(pycurl.URL, statusQuery)
                if not verify_ssl:
                    myQuery.setopt(pycurl.SSL_VERIFYHOST, 0)
                    myQuery.setopt(pycurl.SSL_VERIFYPEER, 0)

                # poll for result here.
                # should be runtimeStatus Completed when finished.
                finished = False
                while not finished:
                    data2 = BytesIO()
                    myQuery.setopt(pycurl.WRITEFUNCTION, data2.write)
                    myQuery.perform()

                    response = json.loads(data2.getvalue())
                    if response["runtimeStatus"] == "Running" or response["runtimeStatus"] == "Pending":
                        time.sleep(4)
                    elif response["runtimeStatus"] == "Completed":
                        # for Azure durable, this is the end of processing.
                        end = datetime.now()
                        status_code = myQuery.getinfo(pycurl.RESPONSE_CODE)
                        finished = True
                    else:
                        self.logging.error(f"failed, request_id = {output['request_id']}")
                        status_code = 500
                        finished = True

            if status_code != 200:
                self.logging.error(
                    "Invocation on URL {} failed with status code {}!".format(url, status_code)
                )
                self.logging.error("Output: {}".format(output))
                raise RuntimeError(f"Failed invocation of function! Output: {output}")

            self.logging.debug("Invoke of function was successful")
            result = ExecutionResult.from_times(begin, end)
            result.times.http_startup = conn_time
            result.times.http_first_byte_return = receive_time

            # OpenWhisk will not return id on a failure
            if "request_id" not in output:
                raise RuntimeError(f"Cannot process allocation with output: {output}")
            result.request_id = output["request_id"]
            self.logging.debug("Request_id: {result.request_id}, end time: {end}")

            # General benchmark output parsing
            result.parse_benchmark_output(output)

            # Azure Durable specific 
            if "output" in response:
                result.output = response["output"]

            return result
        except json.decoder.JSONDecodeError:
            self.logging.error(
                "Invocation on URL {} failed with status code {}!".format(url, status_code)
            )
            if len(data.getvalue()) > 0:
                self.logging.error("Output: {}".format(data.getvalue().decode()))
            else:
                self.logging.error("No output provided!")
            raise RuntimeError(f"Failed invocation of function! Output: {data.getvalue().decode()}")

    def sync_invoke(self, payload: dict) -> ExecutionResult:
        request_id = str(uuid.uuid4())[0:8]
        input = {"payload": payload, "request_id": request_id}
        return self._azure_http_invoke(input, self.url)

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

    @classmethod
    def deserialize(cls, obj:
        """Deserialize trigger from dictionary.

        Args:
            obj: Dictionary containing trigger data

        Returns:
            HTTPTrigger instance with restored configuration.
        """ dict) -> Trigger:
        return HTTPTrigger(obj["url"])
