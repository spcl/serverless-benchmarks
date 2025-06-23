"""AWS trigger implementations for SeBS.

This module provides trigger implementations for AWS Lambda functions,
including library (direct SDK) triggers and HTTP triggers via API Gateway.
Triggers handle function invocation and result processing.

Key classes:
    LibraryTrigger: Direct Lambda SDK invocation trigger
    HTTPTrigger: HTTP API Gateway trigger
"""

import base64
import concurrent.futures
import datetime
import json
from typing import Dict, Optional  # noqa

from sebs.aws.aws import AWS
from sebs.faas.function import ExecutionResult, Trigger


class LibraryTrigger(Trigger):
    """AWS Lambda library trigger for direct SDK invocation.

    This trigger uses the AWS Lambda SDK to directly invoke Lambda functions.
    It provides both synchronous and asynchronous invocation methods with
    comprehensive result parsing and error handling.

    Attributes:
        name: Name of the Lambda function
        _deployment_client: AWS deployment client for Lambda operations
    """

    def __init__(self, fname: str, deployment_client: Optional[AWS] = None) -> None:
        """Initialize the library trigger.

        Args:
            fname: Name of the Lambda function
            deployment_client: AWS deployment client (can be set later)
        """
        super().__init__()
        self.name = fname
        self._deployment_client = deployment_client

    @staticmethod
    def typename() -> str:
        """Get the type name for this trigger.

        Returns:
            str: Type name ('AWS.LibraryTrigger')
        """
        return "AWS.LibraryTrigger"

    @property
    def deployment_client(self) -> AWS:
        """Get the AWS deployment client.

        Returns:
            AWS: AWS deployment client

        Raises:
            AssertionError: If deployment client is not set
        """
        assert self._deployment_client
        return self._deployment_client

    @deployment_client.setter
    def deployment_client(self, deployment_client: AWS) -> None:
        """Set the AWS deployment client.

        Args:
            deployment_client: AWS deployment client to set
        """
        self._deployment_client = deployment_client

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        """Get the trigger type.

        Returns:
            Trigger.TriggerType: LIBRARY trigger type
        """
        return Trigger.TriggerType.LIBRARY

    def sync_invoke(self, payload: dict) -> ExecutionResult:
        """Synchronously invoke the Lambda function.

        Invokes the Lambda function with the provided payload and waits for
        the result. Parses AWS-specific metrics and benchmark output.

        Args:
            payload: Dictionary payload to send to the function

        Returns:
            ExecutionResult: Result of the function execution including metrics
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
        """Asynchronously invoke the Lambda function.

        Triggers the Lambda function asynchronously without waiting for
        the result. Used for fire-and-forget invocations.

        Args:
            payload: Dictionary payload to send to the function

        Returns:
            dict: AWS Lambda invocation response

        Raises:
            RuntimeError: If the async invocation fails
        """

        # FIXME: proper return type
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


class HTTPTrigger(Trigger):
    """AWS API Gateway HTTP trigger for Lambda functions.

    This trigger uses HTTP requests to invoke Lambda functions through
    AWS API Gateway. It provides both synchronous and asynchronous
    invocation methods.

    Attributes:
        url: API Gateway endpoint URL
        api_id: API Gateway API ID
    """

    def __init__(self, url: str, api_id: str) -> None:
        """Initialize the HTTP trigger.

        Args:
            url: API Gateway endpoint URL
            api_id: API Gateway API ID
        """
        super().__init__()
        self.url = url
        self.api_id = api_id

    @staticmethod
    def typename() -> str:
        """Get the type name for this trigger.

        Returns:
            str: Type name ('AWS.HTTPTrigger')
        """
        return "AWS.HTTPTrigger"

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        """Get the trigger type.

        Returns:
            Trigger.TriggerType: HTTP trigger type
        """
        return Trigger.TriggerType.HTTP

    def sync_invoke(self, payload: dict) -> ExecutionResult:
        """Synchronously invoke the function via HTTP.

        Sends an HTTP request to the API Gateway endpoint and waits
        for the response.

        Args:
            payload: Dictionary payload to send to the function

        Returns:
            ExecutionResult: Result of the HTTP invocation
        """
        self.logging.debug(f"Invoke function {self.url}")
        return self._http_invoke(payload, self.url)

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:
        """Asynchronously invoke the function via HTTP.

        Submits the HTTP invocation to a thread pool for asynchronous execution.

        Args:
            payload: Dictionary payload to send to the function

        Returns:
            concurrent.futures.Future: Future object for the async invocation
        """
        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> dict:
        """Serialize the trigger to a dictionary.

        Returns:
            dict: Serialized trigger configuration
        """
        return {"type": "HTTP", "url": self.url, "api-id": self.api_id}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        """Deserialize a trigger from a dictionary.

        Args:
            obj: Dictionary containing trigger configuration

        Returns:
            Trigger: Deserialized HTTPTrigger instance
        """
        return HTTPTrigger(obj["url"], obj["api-id"])
