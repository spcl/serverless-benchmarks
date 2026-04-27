# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
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
import json
from typing import Dict, Optional  # noqa

from sebs.gcp.gcp import GCP
from sebs.gcp.function import FunctionDeploymentType
from sebs.faas.function import ExecutionResult, Trigger


class LibraryTrigger(Trigger):
    """Direct Cloud Functions API trigger for synchronous invocation.

    Uses the Google Cloud Functions API to invoke functions directly through
    the cloud functions client. Provides precise execution timing and error
    handling. Waits for function deployment before invocation.

    Attributes:
        name: Function name to invoke
        _deployment_client: GCP client for API operations
        _deployment_type: Type of deployment (gen1 function or container)
    """

    def __init__(
        self,
        fname: str,
        deployment_client: Optional[GCP] = None,
        deployment_type: Optional[FunctionDeploymentType] = None,
    ) -> None:
        """Initialize library trigger for direct function invocation.

        Args:
            fname: Name of the Cloud Function to invoke
            deployment_client: Optional GCP client for API operations
            deployment_type: Optional deployment type (gen1 function or container)
        """
        super().__init__()
        self.name = fname
        self._deployment_client = deployment_client
        self._deployment_type = deployment_type

    @staticmethod
    def typename() -> str:
        """Get the type name for this trigger implementation.

        Returns:
            Type name string for library triggers
        """
        return "GCP.LibraryTrigger"

    @property
    def deployment_client(self) -> GCP:
        """Get the GCP deployment client.

        Returns:
            GCP client instance for API operations

        Raises:
            AssertionError: If deployment client is not set
        """
        assert self._deployment_client
        return self._deployment_client

    @deployment_client.setter
    def deployment_client(self, deployment_client: GCP) -> None:
        """Set the GCP deployment client.

        Args:
            deployment_client: GCP client instance
        """
        self._deployment_client = deployment_client

    @property
    def deployment_type(self) -> FunctionDeploymentType:
        assert self._deployment_type
        return self._deployment_type

    @deployment_type.setter
    def deployment_type(self, deployment_type: FunctionDeploymentType) -> None:
        self._deployment_type = deployment_type

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        """Get the trigger type for this implementation.

        Returns:
            Library trigger type enum value
        """
        return Trigger.TriggerType.LIBRARY

    def sync_invoke(self, payload: Dict) -> ExecutionResult:
        """Synchronously invoke the Cloud Function using the API.

        Waits for function deployment, then invokes via appropriate API based on
        deployment type:
        - FUNCTION_GEN1: Cloud Functions v1 API
        - CONTAINER: Cloud Run service via HTTP
        - FUNCTION_GEN2: Not yet supported

        Args:
            payload: Input data to send to the function

        Returns:
            ExecutionResult with timing, output, and error information

        Raises:
            NotImplementedError: If deployment type is not supported
        """

        self.logging.info(f"Invoke function {self.name}")

        # Check deployment type and invoke accordingly
        if self._deployment_type == FunctionDeploymentType.FUNCTION_GEN1:
            return self._invoke_gen1_function(payload)
        elif self._deployment_type == FunctionDeploymentType.CONTAINER:
            raise NotImplementedError(
                "LibraryTrigger does not yet support CONTAINER deployment type. "
                "Use HTTPTrigger instead."
            )
        elif self._deployment_type == FunctionDeploymentType.FUNCTION_GEN2:
            raise NotImplementedError(
                "LibraryTrigger does not yet support FUNCTION_GEN2 deployment type. "
                "Use HTTPTrigger instead."
            )
        else:
            raise NotImplementedError(
                f"LibraryTrigger does not support deployment type: {self._deployment_type}. "
                "Please specify deployment_type as FUNCTION_GEN1 or CONTAINER."
            )

    def _invoke_gen1_function(self, payload: Dict) -> ExecutionResult:
        """Invoke a Cloud Functions Gen1 function using the v1 API.

        Args:
            payload: Input data to send to the function

        Returns:
            ExecutionResult with timing, output, and error information
        """
        config = self.deployment_client.config
        full_func_name = (
            f"projects/{config.project_name}/locations/{config.region}/functions/{self.name}"
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
            self.logging.error(f"Invocation of {self.name} failed!")
            self.logging.error(f"Input: {payload}")
            gcp_result.stats.failure = True
            return gcp_result

        output = json.loads(res["result"])
        gcp_result.parse_benchmark_output(output)
        return gcp_result

    def async_invoke(self, payload: Dict) -> concurrent.futures.Future:
        """Asynchronously invoke the Cloud Function.

        Uses a ThreadPoolExecutor to run sync_invoke in the background.

        Args:
            payload: Input data to send to the function

        Returns:
            Future object for the async invocation
        """
        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> Dict:
        """Serialize trigger to dictionary for cache storage.

        Returns:
            Dictionary containing trigger type, name, and deployment type
        """
        return {
            "type": "Library",
            "name": self.name,
            "deployment_type": self._deployment_type.value if self._deployment_type else None,
        }

    @staticmethod
    def deserialize(obj: Dict) -> Trigger:
        """Deserialize trigger from cached configuration.

        Args:
            obj: Dictionary containing serialized trigger data

        Returns:
            Reconstructed LibraryTrigger instance
        """
        deployment_type = None
        if "deployment_type" in obj and obj["deployment_type"] is not None:
            deployment_type = FunctionDeploymentType.deserialize(obj["deployment_type"])

        return LibraryTrigger(obj["name"], deployment_type=deployment_type)


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

    @staticmethod
    def deserialize(obj: Dict) -> Trigger:
        """Deserialize trigger from cached configuration.

        Args:
            obj: Dictionary containing serialized trigger data

        Returns:
            Reconstructed HTTPTrigger instance
        """
        return HTTPTrigger(obj["url"])
