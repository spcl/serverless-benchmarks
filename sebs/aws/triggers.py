# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
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
from enum import Enum
from typing import Dict, Optional  # noqa

from sebs.aws.aws import AWS
from sebs.aws.config import FunctionURLAuthType
from sebs.faas.function import ExecutionResult, Trigger


class HTTPTriggerImplementation(Enum):
    """Internal implementation type for HTTP triggers."""

    API_GATEWAY = "api_gateway"
    FUNCTION_URL = "function_url"


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

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:
        """Asynchronously invoke the Lambda function.

        Triggers the Lambda function asynchronously without waiting for
        the result. Used for fire-and-forget invocations.

        Args:
            payload: Dictionary payload to send to the function

        Returns:
            concurrent.futures.Future: Future object representing the async invocation

        Raises:
            RuntimeError: If the async invocation fails
        """

        # FIXME: proper return type
        self.logging.warning(
            "Async invoke for AWS Lambda library trigger does not wait for completion!"
        )
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

        # Create a completed future with the result
        future: concurrent.futures.Future = concurrent.futures.Future()
        future.set_result(ret)
        return future

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
    """AWS HTTP trigger for Lambda functions.

    This trigger uses HTTP requests to invoke Lambda functions through either
    AWS API Gateway or Lambda Function URLs. The implementation is transparent
    to the user - both are accessed as HTTP triggers.

    Attributes:
        url: HTTP endpoint URL (API Gateway or Function URL)
        implementation: Internal implementation type (API Gateway or Function URL)
        api_id: API Gateway API ID (only for API Gateway implementation)
        function_name: Function name (only for Function URL implementation)
        auth_type: Authentication type (only for Function URL implementation)
    """

    def __init__(
        self,
        url: str,
        implementation: HTTPTriggerImplementation = HTTPTriggerImplementation.API_GATEWAY,
        api_id: Optional[str] = None,
        function_name: Optional[str] = None,
        auth_type: Optional[FunctionURLAuthType] = None,
    ) -> None:
        """Initialize the HTTP trigger.

        Args:
            url: HTTP endpoint URL
            implementation: Implementation type (API Gateway or Function URL)
            api_id: API Gateway API ID (required for API Gateway)
            function_name: Function name (required for Function URL)
            auth_type: Authentication type (for Function URL, defaults to NONE)
        """
        super().__init__()
        self.url = url
        self._implementation = implementation
        self.api_id = api_id
        self.function_name = function_name
        self.auth_type = auth_type if auth_type is not None else FunctionURLAuthType.NONE

    @property
    def implementation(self) -> HTTPTriggerImplementation:
        """Get the implementation type of this HTTP trigger.

        Returns:
            HTTPTriggerImplementation: API_GATEWAY or FUNCTION_URL
        """
        return self._implementation

    @property
    def uses_api_gateway(self) -> bool:
        """Check if this trigger uses API Gateway.

        Returns:
            bool: True if using API Gateway, False otherwise
        """
        return self._implementation == HTTPTriggerImplementation.API_GATEWAY

    @property
    def uses_function_url(self) -> bool:
        """Check if this trigger uses Lambda Function URLs.

        Returns:
            bool: True if using Function URLs, False otherwise
        """
        return self._implementation == HTTPTriggerImplementation.FUNCTION_URL

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

        Sends an HTTP request to the endpoint (API Gateway or Function URL)
        and waits for the response.

        Args:
            payload: Dictionary payload to send to the function

        Returns:
            ExecutionResult: Result of the HTTP invocation

        Raises:
            NotImplementedError: If using AWS_IAM auth with Function URLs
        """
        # Check for unsupported AWS_IAM auth with Function URLs
        if (
            self._implementation == HTTPTriggerImplementation.FUNCTION_URL
            and self.auth_type == FunctionURLAuthType.AWS_IAM
        ):
            raise NotImplementedError(
                "AWS_IAM auth type requires SigV4 signing, which is not yet "
                "implemented for Function URLs. Use auth_type=NONE or "
                "implement SigV4 signing via botocore.auth.SigV4Auth."
            )

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
        pool.shutdown(wait=False)
        return fut

    def serialize(self) -> dict:
        """Serialize the trigger to a dictionary.

        Returns:
            dict: Serialized trigger configuration including implementation details
        """
        base = {
            "type": "HTTP",
            "url": self.url,
            "implementation": self._implementation.value,
        }

        if self._implementation == HTTPTriggerImplementation.API_GATEWAY:
            if self.api_id is not None:
                base["api-id"] = self.api_id
        else:  # FUNCTION_URL
            if self.function_name is not None:
                base["function_name"] = self.function_name
            base["auth_type"] = self.auth_type.value

        return base

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        """Deserialize a trigger from a dictionary.

        Args:
            obj: Dictionary containing trigger configuration

        Returns:
            Trigger: Deserialized HTTPTrigger instance
        """
        # Check for implementation field (new format)
        if "implementation" in obj:
            impl_value = obj["implementation"]
            implementation = HTTPTriggerImplementation(impl_value)

            if implementation == HTTPTriggerImplementation.API_GATEWAY:
                return HTTPTrigger(
                    url=obj["url"],
                    implementation=implementation,
                    api_id=obj.get("api-id"),
                )
            else:  # FUNCTION_URL
                auth_type_str = obj.get("auth_type", "NONE")
                return HTTPTrigger(
                    url=obj["url"],
                    implementation=implementation,
                    function_name=obj.get("function_name"),
                    auth_type=FunctionURLAuthType.from_string(auth_type_str),
                )
        else:
            # Legacy format compatibility - assume API Gateway
            return HTTPTrigger(
                url=obj["url"],
                implementation=HTTPTriggerImplementation.API_GATEWAY,
                api_id=obj.get("api-id"),
            )
