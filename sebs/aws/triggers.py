import base64
import datetime
import json
from typing import Dict, Optional  # noqa


from sebs.aws.aws import AWS
from sebs.faas.function import ExecutionResult, Trigger
from sebs.utils import namedlogging

@namedlogging("AWS.LibraryTrigger")
class LibraryTrigger(Trigger):
    def __init__(self, fname: str, deployment_client: Optional[AWS] = None):
        self.name = fname
        self._deployment_client = deployment_client

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

        self.logging(f"Invoke function {self.name}")

        serialized_payload = json.dumps(payload).encode("utf-8")
        client = self.deployment_client.get_lambda_client()
        begin = datetime.datetime.now()
        ret = client.invoke(
            FunctionName=self.name, Payload=serialized_payload, LogType="Tail"
        )
        end = datetime.datetime.now()

        aws_result = ExecutionResult(begin, end)
        if ret["StatusCode"] != 200:
            logging.error("Invocation of {} failed!".format(self.name))
            logging.error("Input: {}".format(serialized_payload.decode("utf-8")))
            self.deployment_client.get_invocation_error(
                function_name=self.name,
                start_time=int(begin.strftime("%s")) - 1,
                end_time=int(end.strftime("%s")) + 1,
            )
            aws_result.stats.failure = True
            return aws_result
        if "FunctionError" in ret:
            logging.error("Invocation of {} failed!".format(self.name))
            logging.error("Input: {}".format(serialized_payload.decode("utf-8")))
            self.deployment_client.get_invocation_error(
                function_name=self.name,
                start_time=int(begin.strftime("%s")) - 1,
                end_time=int(end.strftime("%s")) + 1,
            )
            aws_result.stats.failure = True
            return aws_result
        self.logging(f"Invoke of function {self.name} was successful")
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

        serialized_payload = json.dumps(payload).encode("utf-8")
        client = self.deployment_client.get_lambda_client()
        ret = client.invoke(
            FunctionName=self.name,
            InvocationType="Event",
            Payload=serialized_payload,
            LogType="Tail",
        )
        if ret["StatusCode"] != 202:
            logging.error("Async invocation of {} failed!".format(self.name))
            logging.error("Input: {}".format(serialized_payload.decode("utf-8")))
            raise RuntimeError()
        return ret

    def serialize(self) -> dict:
        return {"type": "Library", "name": self.name}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return LibraryTrigger(obj["name"])
