import subprocess

from sebs.faas.function import Function, ExecutionResult
import json
import datetime
import requests
import logging


class OpenwhiskFunction(Function):
    def __init__(self, name: str, namespace: str = "_"):
        super().__init__(name)
        self.namespace = namespace

    def sync_invoke(self, payload: dict):
        from tools.openwhisk_preparation import get_openwhisk_url
        ip = get_openwhisk_url()
        command = f"wsk -i action invoke --result {self.name}"
        for key, value in payload.items():
            command = command + f" --param {key} {value}"

        logging.info(f"Function {self.name} of namespace {self.namespace} invoking...")
        error = None
        try:
            begin = datetime.datetime.now()
            response = subprocess.run(
                command.split(),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            end = datetime.datetime.now()
            response = response.stdout.decode("utf-8")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            end = datetime.datetime.now()
            logging.error(f"Cannot synchronously invoke action {self.name}, reason: {e}")
            error = e

        openwhiskResult = ExecutionResult(begin, end)
        if error is not None:
            logging.error("Invocation of {} failed!".format(self.name))
            openwhiskResult.stats.failure = True
            return openwhiskResult

        returnContent = json.loads(response)
        logging.info(f"{returnContent}")

        openwhiskResult.parse_benchmark_output(returnContent)
        return openwhiskResult

    def async_invoke(self, payload: dict):
        from sebs.openwhisk.openwhisk import OpenWhisk
        import time
        import datetime
        ip = OpenWhisk.get_openwhisk_url()
        url = f"https://{ip}/api/v1/namespaces/{self.namespace}/actions/{self.name}?result=true"
        readyPayload = json.dumps(payload)
        logging.info("OpenWhisk url: {}".format(url))
        headers = {"content-type": "application/json",
                   "Authorization": "Basic Nzg5YzQ2YjEtNzFmNi00ZWQ1LThjNTQtODE2YWE0ZjhjNTAyOmFiY3pPM3haQ0xyTU42djJCS0sxZFhZRnBYbFBrY2NPRnFtMTJDZEFzTWdSVTRWck5aOWx5R1ZDR3VNREdJd1A="}

        logging.info(f"Function {self.name} of namespace {self.namespace} invoking...")
        response = requests.request("POST", url, data=readyPayload, headers=headers, verify=False)

        print(
            f"Function {self.name} returned response with code: {response.status_code}"
        )
        if response.status_code != 202:
            logging.error("Invocation of {} failed!".format(self.name))
            logging.error("Input: {}".format(readyPayload))
            logging.error("Input: {}".format(response.content))

            openwhiskResult.stats.failure = True
            return openwhiskResult
        activationId = json.loads(response.content)['activationId']

        url = f"https://{ip}/api/v1/namespaces/_/activations/{activationId}"
        readyPayload = json.dumps(payload)
        headers = {"content-type": "application/json",
                   "Authorization": "Basic Nzg5YzQ2YjEtNzFmNi00ZWQ1LThjNTQtODE2YWE0ZjhjNTAyOmFiY3pPM3haQ0xyTU42djJCS0sxZFhZRnBYbFBrY2NPRnFtMTJDZEFzTWdSVTRWck5aOWx5R1ZDR3VNREdJd1A="}
        begin = datetime.datetime.now()
        attempt = 1
        while True:
            print(f"Function {self.name} of namespace getting result. Attempt: {attempt}")

            response = requests.request("GET", url, data=readyPayload, headers=headers, verify=False)
            if response.status_code == 404:
                time.sleep(0.05)
                attempt += 1
                continue
            break

        print(
            f"Function {self.name} returned response with code: {response.status_code}"
        )
        result = json.loads(response.content)

        if response.status_code != 200:
            logging.error("Invocation of {} failed!".format(self.name))
            logging.error("Input: {}".format(readyPayload))
            logging.error("Input: {}".format(response.content))

            openwhiskResult.stats.failure = True
            return openwhiskResult

        begin = datetime.datetime.fromtimestamp(result['start'] / 1e3)
        end = datetime.datetime.fromtimestamp(result['end'] / 1e3)
        returnContent = result['response']['result']
        openwhiskResult = ExecutionResult(begin, end)
        openwhiskResult.parse_benchmark_output(returnContent)
        return openwhiskResult
