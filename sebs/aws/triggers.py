import base64
import datetime
import json
from typing import Dict, Optional  # noqa

import requests

from sebs.aws.aws import AWS
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

        self.logging.info(f"Invoke function {self.name}")

        serialized_payload = json.dumps(payload).encode("utf-8")
        client = self.deployment_client.get_lambda_client()
        begin = datetime.datetime.now()
        ret = client.invoke(
            FunctionName=self.name, Payload=serialized_payload, LogType="Tail"
        )
        end = datetime.datetime.now()

        import math

        start_time = math.floor(datetime.datetime.timestamp(begin)) - 1
        end_time = math.ceil(datetime.datetime.timestamp(end)) + 1
        aws_result = ExecutionResult.from_times(begin, end)
        if ret["StatusCode"] != 200:
            self.logging.error("Invocation of {} failed!".format(self.name))
            self.logging.error("Input: {}".format(serialized_payload.decode("utf-8")))
            self.deployment_client.get_invocation_error(
                function_name=self.name, start_time=start_time, end_time=end_time
            )
            aws_result.stats.failure = True
            return aws_result
        if "FunctionError" in ret:
            self.logging.error("Invocation of {} failed!".format(self.name))
            self.logging.error("Input: {}".format(serialized_payload.decode("utf-8")))
            self.deployment_client.get_invocation_error(
                function_name=self.name, start_time=start_time, end_time=end_time
            )
            aws_result.stats.failure = True
            return aws_result
        self.logging.info(f"Invoke of function {self.name} was successful")
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

        self.logging.info(f"Invoke function {self.url}")
        import pycurl
        from io import BytesIO
        c = pycurl.Curl()
        c.setopt(pycurl.HTTPHEADER, ['Content-Type: application/json'])
        c.setopt(pycurl.POST, 1)
        c.setopt(pycurl.URL, self.url)
        data = BytesIO()
        c.setopt(c.WRITEFUNCTION, data.write)


        #body_as_json_string = json.dumps(payload)
        #body_as_file_object = StringIO(body_as_json_string)
        c.setopt(pycurl.POSTFIELDS, json.dumps(payload))
        #begin = datetime.datetime.now()
        #ret = requests.request(method="POST", url=self.url, json=payload)
        #end = datetime.datetime.now()
        begin = datetime.datetime.now()
        c.perform()
        #ret = requests.request(method="POST", url=self.url, json=payload)
        end = datetime.datetime.now()
        status_code = c.getinfo(pycurl.RESPONSE_CODE)
        conn_time = c.getinfo(pycurl.PRETRANSFER_TIME)
        output = json.loads(data.getvalue())
        print(output)

        if status_code != 200:
            self.logging.error("Invocation on URL {} failed!".format(self.url))
            #self.logging.error("Input: {}".format(payload))
            self.logging.error("Output: {}".format(output))
            raise RuntimeError("Failed synchronous invocation of AWS Lambda function!")

        self.logging.info(f"Invoke of function was successful")
        #output = ret.json()
        result = ExecutionResult.from_times(begin, end)
        result.request_id = output["request_id"]
        # General benchmark output parsing
        result.parse_benchmark_output(output)
        return result, conn_time, begin

    def async_invoke(self, payload: dict) -> ExecutionResult:
        import concurrent

        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> dict:
        return {"type": "HTTP", "url": self.url, "api-id": self.api_id}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return HTTPTrigger(obj["url"], obj["api-id"])
