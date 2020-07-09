from sebs.faas.function import Function, ExecutionResult


class OpenWhiskFunction(Function):
    def sync_invoke(self, payload: dict):
        url = "http://localhost:5051/benchmark"
        readyPayload = json.dumps(payload)
        headers = {"content-type": "application/json"}
        begin = datetime.datetime.now()
        logging.info(f"Function {self.name} invoking...")
        response = requests.request("POST", url, data=readyPayload, headers=headers)
        end = datetime.datetime.now()
        logging.info(
            f"Function {self.name} returned response with code: {response.status_code}"
        )
        openwhiskResult = ExecutionResult(begin, end)
        if response.status_code != 200:
            logging.error("Invocation of {} failed!".format(self.name))
            logging.error("Input: {}".format(readyPayload))

            openwhiskResult.stats.failure = True
            return openwhiskResult
        returnContent = json.loads(json.loads(response.content))
        openwhiskResult.parse_benchmark_output(returnContent)
        return openwhiskResult

    def async_invoke(self, payload: dict):
        raise Exception("Non-trigger invoke not supported!")