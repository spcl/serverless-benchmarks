# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
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
import time
from datetime import datetime
from io import BytesIO
from typing import Any, cast, Dict, Optional  # noqa

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


class WorkflowHTTPTrigger(HTTPTrigger):
    """HTTP-backed trigger for Azure Durable Function workflows.

    Azure starts Durable Functions workflows through an HTTP endpoint, but SeBS
    treats workflows as library triggers and validates the workflow result
    directly. This trigger keeps the Azure HTTP transport while exposing the
    same result shape as AWS Step Functions and Cloudflare Workflows.
    """

    @staticmethod
    def typename() -> str:
        """Return the canonical type name for this trigger class."""
        return "Azure.WorkflowHTTPTrigger"

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        """Get the trigger type."""
        return Trigger.TriggerType.LIBRARY

    def sync_invoke(self, payload: dict) -> ExecutionResult:
        """Synchronously invoke an Azure Durable Function workflow."""
        begin = datetime.now()
        status_code, raw, conn_time, receive_time = self._http_post_json(
            self.url, payload, timeout=300
        )
        envelope = self._parse_json_response(raw, self.url)

        if status_code not in [200, 202]:
            self.logging.error(f"Invocation on URL {self.url} failed!")
            self.logging.error(f"Output: {envelope}")
            raise RuntimeError(f"Failed invocation of function! Output: {envelope}")

        workflow_result = envelope.get("result")
        if isinstance(workflow_result, dict) and "statusQueryGetUri" in workflow_result:
            workflow_result = self._poll_workflow_status(
                workflow_result["statusQueryGetUri"], begin
            )

        end = datetime.now()
        result = ExecutionResult.from_times(begin, end)
        cast(Any, result.times).http_startup = conn_time
        cast(Any, result.times).http_first_byte_return = receive_time
        result.request_id = envelope.get("request_id", "")

        parsed_output = dict(envelope)
        parsed_output["result"] = workflow_result
        parsed_output["end"] = f"{end.timestamp():.6f}"
        result.parse_benchmark_output(parsed_output)
        result.output = cast(dict, workflow_result)
        return result

    def _http_post_json(
        self, url: str, payload: dict, timeout: int
    ) -> tuple[int, bytes, float, float]:
        """POST JSON and return status, body, connection time, and first-byte time."""
        import pycurl

        c = pycurl.Curl()
        c.setopt(pycurl.HTTPHEADER, ["Content-Type: application/json"])
        c.setopt(pycurl.POST, 1)
        c.setopt(pycurl.URL, url)
        c.setopt(pycurl.POSTFIELDS, json.dumps(payload))
        c.setopt(pycurl.TIMEOUT, timeout)
        data = BytesIO()
        c.setopt(pycurl.WRITEFUNCTION, data.write)
        c.perform()
        status_code = c.getinfo(pycurl.RESPONSE_CODE)
        conn_time = c.getinfo(pycurl.PRETRANSFER_TIME)
        receive_time = c.getinfo(pycurl.STARTTRANSFER_TIME)
        c.close()
        return status_code, data.getvalue(), conn_time, receive_time

    def _http_get(self, url: str, timeout: int) -> tuple[int, bytes]:
        """GET a URL and return status and body."""
        import pycurl

        c = pycurl.Curl()
        c.setopt(pycurl.URL, url)
        c.setopt(pycurl.TIMEOUT, timeout)
        data = BytesIO()
        c.setopt(pycurl.WRITEFUNCTION, data.write)
        c.perform()
        status_code = c.getinfo(pycurl.RESPONSE_CODE)
        c.close()
        return status_code, data.getvalue()

    def _parse_json_response(self, raw: bytes, url: str) -> dict:
        """Parse a JSON response or raise a useful invocation error."""
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            text = raw.decode(errors="replace")
            self.logging.error(f"Invocation on URL {url} failed!")
            self.logging.error(f"Output: {text if text else 'No output provided!'}")
            raise RuntimeError(f"Failed invocation of function! Output: {text}") from None

    def _poll_workflow_status(self, status_url: str, begin: datetime) -> Any:
        """Poll Azure Durable Functions status until the workflow completes."""
        max_poll_time = 7200
        poll_interval = 5

        while (datetime.now() - begin).total_seconds() < max_poll_time:
            status_code, raw = self._http_get(status_url, timeout=60)
            status = self._parse_json_response(raw, status_url)

            if status_code not in [200, 202]:
                self.logging.warning(
                    f"Workflow status poll failed with status={status_code}: {status}"
                )
                time.sleep(poll_interval)
                continue

            runtime_status = status.get("runtimeStatus")
            if runtime_status == "Completed":
                return status.get("output")
            if runtime_status in ["Failed", "Terminated", "Canceled"]:
                self.logging.error(f"Workflow execution failed: {status}")
                raise RuntimeError(f"Workflow execution failed: {status}")

            time.sleep(poll_interval)

        raise RuntimeError(f"Workflow did not complete within {max_poll_time}s")

    def serialize(self) -> dict:
        """Serialize trigger to dictionary."""
        return {"type": self.typename(), "url": self.url}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        """Deserialize trigger from dictionary."""
        return WorkflowHTTPTrigger(obj["url"])
