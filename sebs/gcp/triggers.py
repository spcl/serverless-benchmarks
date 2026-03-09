"""Trigger implementations for Google Cloud Functions.

This module provides trigger classes for invoking Cloud Functions through different
mechanisms including direct library calls and HTTP requests. Supports both
synchronous and asynchronous invocation patterns.

Classes:
    LibraryTrigger: Direct Cloud Functions API invocation trigger
    HTTPTrigger: HTTP endpoint invocation trigger

Example:
    Using a library trigger for direct invocation:

        trigger = LibraryTrigger("my-function", gcp_client)
        result = trigger.sync_invoke({"input": "data"})
    Using an HTTP trigger:

        trigger = HTTPTrigger("https://region-project.cloudfunctions.net/my-function")
        result = trigger.sync_invoke({"input": "data"})
"""

import concurrent.futures
import datetime
import uuid
import json
import time
from typing import Dict, Optional  # noqa

from google.cloud.workflows.executions_v1beta import ExecutionsClient
from google.cloud.workflows.executions_v1beta.types import Execution

from sebs.gcp.gcp import GCP
from sebs.faas.function import ExecutionResult, Trigger


class LibraryTrigger(Trigger):
    def __init__(self, name: str, deployment_client: Optional[GCP] = None):
        super().__init__()
        self.name = name
        self.deployment_client = deployment_client

    @staticmethod
    def typename() -> str:
        return "GCP.LibraryTrigger"

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.LIBRARY

    def sync_invoke(self, payload: Dict) -> ExecutionResult:
        raise NotImplementedError()

    def async_invoke(self, payload: Dict):
        raise NotImplementedError()

    def serialize(self) -> dict:
        """Serialize the trigger to a dictionary.

        Returns:
            dict: Serialized trigger configuration
        """
        return {"type": "Library", "name": self.name}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        """Deserialize a trigger from a dictionary.

        Args:
            obj: Dictionary containing trigger configuration

        Returns:
            Trigger: Deserialized LibraryTrigger instance
        """
        return LibraryTrigger(obj["name"])


class WorkflowLibraryTrigger(LibraryTrigger):
    def sync_invoke(self, payload: dict) -> ExecutionResult:

        self.logging.debug(f"Invoke workflow {self.name}")

        request_id = str(uuid.uuid4())[0:8]
        input = {"payload": payload, "request_id": request_id}

        client = ExecutionsClient()
        begin = datetime.datetime.now()
        execution = Execution(argument=json.dumps(input))
        ret = client.create_execution(parent=self.name, execution=execution)
        end = datetime.datetime.now()

        gcp_result = ExecutionResult.from_times(begin, end)
        gcp_result.request_id = request_id

        # Wait for execution to finish
        execution_finished = False
        while not execution_finished:
            execution = client.get_execution(name=ret.name)
            execution_finished = execution.state != Execution.State.ACTIVE

            # If we haven't seen the result yet, wait a second.
            if not execution_finished:
                time.sleep(1)
            elif execution.state == Execution.State.FAILED:
                self.logging.error(f"Invocation of {self.name} failed")
                self.logging.error(f"Input: {payload}")
                gcp_result.stats.failure = True
                return gcp_result

        gcp_result.output = json.loads(execution.result)["payload"]

        return gcp_result

    def async_invoke(self, payload: dict):
        raise NotImplementedError("Async invocation is not implemented")


class HTTPTrigger(Trigger):
    """HTTP endpoint trigger for Cloud Functions invocation.

    Invokes Cloud Functions through their HTTP endpoints, supporting both
    synchronous and asynchronous execution patterns using HTTP requests.

    Attributes:
        url: HTTP endpoint URL for the Cloud Function
    """

    def __init__(self, url: str) -> None:
        """Initialize HTTP trigger with function endpoint URL.

        Args:
            url: HTTP endpoint URL for the Cloud Function
        """
        super().__init__()
        self.url = url

    @staticmethod
    def typename() -> str:
        """Get the type name for this trigger implementation.

        Returns:
            Type name string for HTTP triggers
        """
        return "GCP.HTTPTrigger"

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        """Get the trigger type for this implementation.

        Returns:
            HTTP trigger type enum value
        """
        return Trigger.TriggerType.HTTP

    def sync_invoke(self, payload: Dict) -> ExecutionResult:
        """Synchronously invoke the Cloud Function via HTTP.

        Args:
            payload: Input data to send to the function

        Returns:
            ExecutionResult from the HTTP invocation
        """

        self.logging.debug(f"Invoke function {self.url}")
        return self._http_invoke(payload, self.url)

    def async_invoke(self, payload: Dict) -> concurrent.futures.Future:
        """Asynchronously invoke the Cloud Function via HTTP.

        Args:
            payload: Input data to send to the function

        Returns:
            Future object for the async HTTP invocation
        """
        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> Dict:
        """Serialize trigger to dictionary for cache storage.

        Returns:
            Dictionary containing trigger type and URL
        """
        return {"type": "HTTP", "url": self.url}

    @classmethod
    def deserialize(cls, obj: dict) -> Trigger:
        """Deserialize trigger from cached configuration.

        Args:
            obj: Dictionary containing serialized trigger data

        Returns:
            Reconstructed HTTPTrigger instance
        """
        return HTTPTrigger(obj["url"])
