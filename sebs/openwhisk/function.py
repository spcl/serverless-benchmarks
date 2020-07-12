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
        from sebs.openwhisk.openwhisk import OpenWhisk
        ip = OpenWhisk.get_openwhisk_url()
        url = f"https://{ip}/api/v1/namespaces/{self.namespace}/actions/{self.name}?result=true&blocking=true"
        readyPayload = json.dumps(payload)

        headers = {"content-type": "application/json",
            "Authorization": "Basic Nzg5YzQ2YjEtNzFmNi00ZWQ1LThjNTQtODE2YWE0ZjhjNTAyOmFiY3pPM3haQ0xyTU42djJCS0sxZFhZRnBYbFBrY2NPRnFtMTJDZEFzTWdSVTRWck5aOWx5R1ZDR3VNREdJd1A="}
        begin = datetime.datetime.now()
        logging.info(f"Function {self.name} of namespace {self.namespace} invoking...")
        response = requests.request("POST", url, data=readyPayload, headers=headers, verify=False)
        end = datetime.datetime.now()
        print(
            f"Function {self.name} returned response with code: {response.status_code}"
        )
        openwhiskResult = ExecutionResult(begin, end)
        if response.status_code != 200:
            logging.error("Invocation of {} failed!".format(self.name))
            logging.error("Input: {}".format(readyPayload))
            logging.error("Input: {}".format(response.content))

            openwhiskResult.stats.failure = True
            return openwhiskResult
        returnContent = json.loads(response.content)

        openwhiskResult.parse_benchmark_output(returnContent)
        return openwhiskResult

    def async_invoke(self, payload: dict):
        from sebs.openwhisk.openwhisk import OpenWhisk
        import time
        import datetime
        ip = OpenWhisk.get_openwhisk_url()
        url = f"https://{ip}/api/v1/namespaces/{self.namespace}/actions/{self.name}?result=true"
        readyPayload = json.dumps(payload)
        print(url)
        headers = {"content-type": "application/json",
            "Authorization": "Basic Nzg5YzQ2YjEtNzFmNi00ZWQ1LThjNTQtODE2YWE0ZjhjNTAyOmFiY3pPM3haQ0xyTU42djJCS0sxZFhZRnBYbFBrY2NPRnFtMTJDZEFzTWdSVTRWck5aOWx5R1ZDR3VNREdJd1A="}
        begin = datetime.datetime.now()
        logging.info(f"Function {self.name} of namespace {self.namespace} invoking...")
        response = requests.request("POST", url, data=readyPayload, headers=headers, verify=False)
        end = datetime.datetime.now()
        print(
            f"Function {self.name} returned response with code: {response.status_code}"
        )
        openwhiskResult = ExecutionResult(begin, end)
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
        while(True):
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
        print(result)
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