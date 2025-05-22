import concurrent.futures
import datetime
import json
import time
from typing import Dict, Optional  # noqa

from sebs.gcp.gcp import GCP
from sebs.faas.function import ExecutionResult, Trigger


class LibraryTrigger(Trigger):
    """
    Represents a library-based trigger for Google Cloud Functions, invoking them
    directly using the Google Cloud Functions API client.
    """
    def __init__(self, fname: str, deployment_client: Optional[GCP] = None):
        """
        Initialize a LibraryTrigger.

        :param fname: Name of the Google Cloud Function.
        :param deployment_client: Optional GCP client for deployment and invocation.
        """
        super().__init__()
        self.name = fname
        self._deployment_client = deployment_client

    @staticmethod
    def typename() -> str:
        """Return the type name of this trigger implementation."""
        return "GCP.LibraryTrigger"

    @property
    def deployment_client(self) -> GCP:
        """GCP client used for deploying and invoking the function."""
        assert self._deployment_client, "Deployment client not set for LibraryTrigger"
        return self._deployment_client

    @deployment_client.setter
    def deployment_client(self, deployment_client: GCP):
        """Set the GCP client."""
        self._deployment_client = deployment_client

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        """Return the type of this trigger (LIBRARY)."""
        return Trigger.TriggerType.LIBRARY

    def sync_invoke(self, payload: dict) -> ExecutionResult:
        """
        Synchronously invoke the Google Cloud Function using the functions API.

        Ensures the function is deployed and active before invocation.

        :param payload: Input payload for the function.
        :return: ExecutionResult object containing invocation details and metrics.
        :raises RuntimeError: If the invocation fails or returns an error.
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

    def async_invoke(self, payload: dict):
        """
        Asynchronously invoke the Google Cloud Function.

        Note: This method is not currently implemented for GCP's LibraryTrigger.
        GCP's `functions.call` API is synchronous. Asynchronous behavior would
        need to be implemented using a thread pool or similar mechanism if desired.

        :param payload: Input payload for the function.
        :raises NotImplementedError: This feature is not implemented.
        """
        raise NotImplementedError("Asynchronous invocation via library is not implemented for GCP.")

    def serialize(self) -> dict:
        """
        Serialize the LibraryTrigger to a dictionary.

        :return: Dictionary representation of the trigger.
        """
        return {"type": "Library", "name": self.name}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        """
        Deserialize a LibraryTrigger from a dictionary.

        :param obj: Dictionary representation of the trigger.
        :return: A new LibraryTrigger instance.
        """
        return LibraryTrigger(obj["name"])


class HTTPTrigger(Trigger):
    """
    Represents an HTTP-based trigger for a Google Cloud Function,
    invoked via its public URL.
    """
    def __init__(self, url: str):
        """
        Initialize an HTTPTrigger.

        :param url: The invocation URL for the HTTP-triggered function.
        """
        super().__init__()
        self.url = url

    @staticmethod
    def typename() -> str:
        """Return the type name of this trigger implementation."""
        return "GCP.HTTPTrigger"

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        """Return the type of this trigger (HTTP)."""
        return Trigger.TriggerType.HTTP

    def sync_invoke(self, payload: dict) -> ExecutionResult:
        """
        Synchronously invoke the Google Cloud Function via its HTTP endpoint.

        :param payload: Input payload for the function (will be sent as JSON).
        :return: ExecutionResult object containing invocation details and metrics.
        """
        self.logging.debug(f"Invoke function {self.url}")
        # Assuming verify_ssl=True is the default desired behavior for GCP HTTP triggers
        return self._http_invoke(payload, self.url, verify_ssl=True)

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:
        """
        Asynchronously invoke the Google Cloud Function via its HTTP endpoint.

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
