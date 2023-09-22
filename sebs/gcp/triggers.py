import concurrent.futures
import datetime
import json
import time
from typing import Dict, Optional  # noqa

from sebs.gcp.gcp import GCP
from sebs.faas.function import ExecutionResult, Trigger


class LibraryTrigger(Trigger):
    def __init__(self, fname: str, deployment_client: Optional[GCP] = None):
        super().__init__()
        self.name = fname
        self._deployment_client = deployment_client

    @staticmethod
    def typename() -> str:
        return "GCP.LibraryTrigger"

    @property
    def deployment_client(self) -> GCP:
        assert self._deployment_client
        return self._deployment_client

    @deployment_client.setter
    def deployment_client(self, deployment_client: GCP):
        self._deployment_client = deployment_client

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.LIBRARY

    def sync_invoke(self, payload: dict) -> ExecutionResult:

        self.logging.info(f"Invoke function {self.name}")

        # Verify that the function is deployed
        deployed = False
        while not deployed:
            if self.deployment_client.is_deployed(self.name):
                deployed = True
            else:
                time.sleep(5)

        # GCP's fixed style for a function name
        config = self.deployment_client.config
        full_func_name = (
            f"projects/{config.project_name}/locations/" f"{config.region}/functions/{self.name}"
        )
        function_client = self.deployment_client.get_function_client()
        req = (
            function_client.projects()
            .locations()
            .functions()
            .call(name=full_func_name, body={"data": json.dumps(payload)})
        )
        begin = datetime.datetime.now()
        res = req.execute()
        end = datetime.datetime.now()

        gcp_result = ExecutionResult.from_times(begin, end)
        gcp_result.request_id = res["executionId"]
        if "error" in res.keys() and res["error"] != "":
            self.logging.error("Invocation of {} failed!".format(self.name))
            self.logging.error("Input: {}".format(payload))
            gcp_result.stats.failure = True
            return gcp_result

        output = json.loads(res["result"])
        gcp_result.parse_benchmark_output(output)
        return gcp_result

    def async_invoke(self, payload: dict):
        raise NotImplementedError()

    def serialize(self) -> dict:
        return {"type": "Library", "name": self.name}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return LibraryTrigger(obj["name"])


class HTTPTrigger(Trigger):
    def __init__(self, url: str):
        super().__init__()
        self.url = url

    @staticmethod
    def typename() -> str:
        return "GCP.HTTPTrigger"

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
        return {"type": "HTTP", "url": self.url}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return HTTPTrigger(obj["url"])
