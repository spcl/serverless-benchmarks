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
import time
from typing import Dict, Optional  # noqa

from sebs.gcp.gcp import GCP
from sebs.faas.function import ExecutionResult, Trigger


class LibraryTrigger(Trigger):
    """Direct Cloud Functions API trigger for synchronous invocation.
    
    Uses the Google Cloud Functions API to invoke functions directly through
    the cloud functions client. Provides precise execution timing and error
    handling. Waits for function deployment before invocation.
    
    Attributes:
        name: Function name to invoke
        _deployment_client: GCP client for API operations
    """
    def __init__(self, fname: str, deployment_client: Optional[GCP] = None) -> None:
        """Initialize library trigger for direct function invocation.
        
        Args:
            fname: Name of the Cloud Function to invoke
            deployment_client: Optional GCP client for API operations
        """
        super().__init__()
        self.name = fname
        self._deployment_client = deployment_client

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

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        """Get the trigger type for this implementation.
        
        Returns:
            Library trigger type enum value
        """
        return Trigger.TriggerType.LIBRARY

    def sync_invoke(self, payload: Dict) -> ExecutionResult:
        """Synchronously invoke the Cloud Function using the API.
        
        Waits for function deployment, then invokes via Cloud Functions API.
        Measures execution time and handles errors.
        
        Args:
            payload: Input data to send to the function
            
        Returns:
            ExecutionResult with timing, output, and error information
        """

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

    def async_invoke(self, payload: Dict):
        """Asynchronously invoke the Cloud Function.
        
        Args:
            payload: Input data to send to the function
            
        Raises:
            NotImplementedError: Async invocation not implemented for library triggers
        """
        raise NotImplementedError()

    def serialize(self) -> Dict:
        """Serialize trigger to dictionary for cache storage.
        
        Returns:
            Dictionary containing trigger type and name
        """
        return {"type": "Library", "name": self.name}

    @staticmethod
    def deserialize(obj: Dict) -> Trigger:
        """Deserialize trigger from cached configuration.
        
        Args:
            obj: Dictionary containing serialized trigger data
            
        Returns:
            Reconstructed LibraryTrigger instance
        """
        return LibraryTrigger(obj["name"])


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
