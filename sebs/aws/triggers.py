import base64
import concurrent.futures
import datetime
import json
from typing import Dict, Optional  # noqa

from sebs.aws.aws import AWS
from sebs.aws.config import FunctionURLAuthType
from sebs.faas.function import ExecutionResult, Trigger


class LibraryTrigger(Trigger):
    def __init__(self, fname: str, deployment_client: Optional[AWS] = None):
        super().__init__()
        self.name = fname
        self._deployment_client = deployment_client

    @staticmethod
    def typename() -> str:
        return "AWS.LibraryTrigger"

    @property
    def deployment_client(self) -> AWS:
        assert self._deployment_client
        return self._deployment_client

    @deployment_client.setter
    def deployment_client(self, deployment_client: AWS):
        self._deployment_client = deployment_client

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.LIBRARY

    def sync_invoke(self, payload: dict) -> ExecutionResult:

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

    def async_invoke(self, payload: dict):

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
        return {"type": "Library", "name": self.name}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return LibraryTrigger(obj["name"])


class HTTPTrigger(Trigger):
    def __init__(self, url: str, api_id: str):
        super().__init__()
        self.url = url
        self.api_id = api_id

    @staticmethod
    def typename() -> str:
        return "AWS.HTTPTrigger"

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.HTTP

    def sync_invoke(self, payload: dict) -> ExecutionResult:

        self.logging.debug(f"Invoke function {self.url}")
        return self._http_invoke(payload, self.url)

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:

        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> dict:
        return {"type": "HTTP", "url": self.url, "api-id": self.api_id}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return HTTPTrigger(obj["url"], obj["api-id"])


class FunctionURLTrigger(Trigger):
    """
    Trigger using AWS Lambda Function URLs instead of API Gateway.
    Function URLs provide a simpler alternative without the 29-second timeout limit.
    """

    def __init__(
        self,
        url: str,
        function_name: str,
        auth_type: FunctionURLAuthType = FunctionURLAuthType.NONE,
    ):
        super().__init__()
        self.url = url
        self.function_name = function_name
        self.auth_type = auth_type

    @staticmethod
    def typename() -> str:
        return "AWS.FunctionURLTrigger"

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.HTTP

    def sync_invoke(self, payload: dict) -> ExecutionResult:
        self.logging.debug(f"Invoke function via Function URL {self.url}")
        if self.auth_type == FunctionURLAuthType.AWS_IAM:
            raise NotImplementedError(
                "AWS_IAM auth type requires SigV4 signing, which is not yet "
                "implemented in FunctionURLTrigger. Use auth_type=NONE or "
                "implement SigV4 signing via botocore.auth.SigV4Auth."
            )
        return self._http_invoke(payload, self.url)

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:
        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        pool.shutdown(wait=False)
        return fut

    def serialize(self) -> dict:
        return {
            "type": "FunctionURL",
            "url": self.url,
            "function_name": self.function_name,
            "auth_type": self.auth_type.value,
        }

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        auth_type_str = obj.get("auth_type", "NONE")
        return FunctionURLTrigger(
            obj["url"],
            obj["function_name"],
            FunctionURLAuthType.from_string(auth_type_str),
        )
