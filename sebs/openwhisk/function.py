from sebs.faas.function import Function, ExecutionResult
import json
import datetime
import requests
import logging


class OpenwhiskFunction(Function):
    def __init__(self, name: str, namespace: str = "guest"):
        super().__init__(name)
        self.namespace = namespace

    def sync_invoke(self, payload: dict):
        url = f"http://172.17.0.1:3233/api/v1/namespaces/{self.namespace}/actions/{self.name}?blocking=true&result=true"
        readyPayload = json.dumps(payload)
        headers = {"content-type": "application/json",
            "Authorization": "Basic Nzg5YzQ2YjEtNzFmNi00ZWQ1LThjNTQtODE2YWE0ZjhjNTAyOmFiY3pPM3haQ0xyTU42djJCS0sxZFhZRnBYbFBrY2NPRnFtMTJDZEFzTWdSVTRWck5aOWx5R1ZDR3VNREdJd1A="}
        begin = datetime.datetime.now()
        logging.info(f"Function {self.name} of namespace {self.namespace} invoking...")
        response = requests.request("POST", url, data=readyPayload, headers=headers)
        end = datetime.datetime.now()
        print(
            f"Function {self.name} returned response with code: {response.status_code}"
        )
        openwhiskResult = ExecutionResult(begin, end)
        if response.status_code != 200:
            logging.error("Invocation of {} failed!".format(self.name))
            logging.error("Input: {}".format(readyPayload))

            openwhiskResult.stats.failure = True
            return openwhiskResult
        returnContent = json.loads(response.content)
        openwhiskResult.parse_benchmark_output(returnContent)
        return openwhiskResult

    def async_invoke(self, payload: dict):
        raise Exception("Non-trigger invoke not supported!")