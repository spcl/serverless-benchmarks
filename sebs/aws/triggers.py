import base64
import concurrent.futures
import datetime
import json
from typing import Dict, Optional  # noqa

from sebs.aws.aws import AWS
from sebs.faas.function import ExecutionResult, Trigger


class LibraryTrigger(Trigger):
    """
    Represents a library-based trigger for AWS Lambda, invoking functions directly
    using the AWS SDK.
    """
    def __init__(self, fname: str, deployment_client: Optional[AWS] = None):
        """
        Initialize a LibraryTrigger.

        :param fname: Name of the Lambda function.
        :param deployment_client: Optional AWS client for deployment and invocation.
        """
        super().__init__()
        self.name = fname
        self._deployment_client = deployment_client

    @staticmethod
    def typename() -> str:
        """Return the type name of this trigger implementation."""
        return "AWS.LibraryTrigger"

    @property
    def deployment_client(self) -> AWS:
        """AWS client used for deploying and invoking the function."""
        assert self._deployment_client
        return self._deployment_client

    @deployment_client.setter
    def deployment_client(self, deployment_client: AWS):
        """Set the AWS client."""
        self._deployment_client = deployment_client

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        """Return the type of this trigger (LIBRARY)."""
        return Trigger.TriggerType.LIBRARY

    def sync_invoke(self, payload: dict) -> ExecutionResult:
        """
        Synchronously invoke the Lambda function.

        :param payload: Input payload for the function.
        :return: ExecutionResult object containing invocation details and metrics.
        """
        self.logging.debug(f"Invoke function {self.name}")

        serialized_payload = json.dumps(payload).encode("utf-8")
        client = self.deployment_client.get_lambda_client()
        begin = datetime.datetime.now()
        ret = client.invoke(FunctionName=self.name, Payload=serialized_payload, LogType="Tail")
        end = datetime.datetime.now()

        aws_result = ExecutionResult.from_times(begin, end)
        aws_result.request_id = ret["ResponseMetadata"]["RequestId"]
        if ret["StatusCode"] != 200:
            self.logging.error("Invocation of {} failed!".format(self.name))
            self.logging.error("Input: {}".format(serialized_payload.decode("utf-8")))
            aws_result.stats.failure = True
            return aws_result
        if "FunctionError" in ret:
            self.logging.error("Invocation of {} failed!".format(self.name))
            self.logging.error("Input: {}".format(serialized_payload.decode("utf-8")))
            aws_result.stats.failure = True
            return aws_result
        self.logging.debug(f"Invoke of function {self.name} was successful")
        log = base64.b64decode(ret["LogResult"])
        function_output = json.loads(ret["Payload"].read().decode("utf-8"))

        # AWS-specific parsing
        AWS.parse_aws_report(log.decode("utf-8"), aws_result)
        # General benchmark output parsing
        # For some reason, the body is dict for NodeJS but a serialized JSON for Python
        if isinstance(function_output["body"], dict):
            aws_result.parse_benchmark_output(function_output["body"])
        else:
            aws_result.parse_benchmark_output(json.loads(function_output["body"]))
        return aws_result

    def async_invoke(self, payload: dict) -> dict:
        """
        Asynchronously invoke the Lambda function.

        Note: The return type 'dict' is based on the boto3 client.invoke response
        when InvocationType is 'Event'. It might be beneficial to define a more
        specific return type or structure if more details from the response are needed.

        :param payload: Input payload for the function.
        :return: Dictionary containing the response from the Lambda invoke call (e.g., StatusCode, RequestId).
        :raises RuntimeError: If the asynchronous invocation fails (status code is not 202).
        """
        # FIXME: proper return type - consider a dataclass for the response
        serialized_payload = json.dumps(payload).encode("utf-8")
        client = self.deployment_client.get_lambda_client()
        ret = client.invoke(
            FunctionName=self.name,
            InvocationType="Event",
            Payload=serialized_payload,
            LogType="Tail",
        )
        if ret["StatusCode"] != 202:
            self.logging.error("Async invocation of {} failed!".format(self.name))
            self.logging.error("Input: {}".format(serialized_payload.decode("utf-8")))
            raise RuntimeError()
        return ret

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
    Represents an HTTP-based trigger for AWS Lambda, typically via API Gateway.
    """
    def __init__(self, url: str, api_id: str):
        """
        Initialize an HTTPTrigger.

        :param url: The invocation URL for the HTTP endpoint.
        :param api_id: The API ID of the API Gateway.
        """
        super().__init__()
        self.url = url
        self.api_id = api_id

    @staticmethod
    def typename() -> str:
        """Return the type name of this trigger implementation."""
        return "AWS.HTTPTrigger"

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        """Return the type of this trigger (HTTP)."""
        return Trigger.TriggerType.HTTP

    def sync_invoke(self, payload: dict) -> ExecutionResult:
        """
        Synchronously invoke the Lambda function via its HTTP endpoint.

        :param payload: Input payload for the function (will be sent as JSON).
        :return: ExecutionResult object containing invocation details and metrics.
        """
        self.logging.debug(f"Invoke function {self.url}")
        return self._http_invoke(payload, self.url)

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:
        """
        Asynchronously invoke the Lambda function via its HTTP endpoint.

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

        :return: Dictionary representation of the trigger.
        """
        return {"type": "HTTP", "url": self.url, "api-id": self.api_id}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        """
        Deserialize an HTTPTrigger from a dictionary.

        :param obj: Dictionary representation of the trigger.
        :return: A new HTTPTrigger instance.
        """
        return HTTPTrigger(obj["url"], obj["api-id"])
