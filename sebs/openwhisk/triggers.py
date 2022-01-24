import concurrent.futures
import datetime
import json
import subprocess
from typing import Dict, List, Optional  # noqa

from sebs.faas.function import ExecutionResult, Trigger


class LibraryTrigger(Trigger):
    def __init__(self, fname: str, wsk_cmd: Optional[List[str]] = None):
        super().__init__()
        self.fname = fname
        if wsk_cmd:
            self._wsk_cmd = [*wsk_cmd, "action", "invoke", "--result", self.fname]

    @staticmethod
    def trigger_type() -> "Trigger.TriggerType":
        return Trigger.TriggerType.LIBRARY

    @property
    def wsk_cmd(self) -> List[str]:
        assert self._wsk_cmd
        return self._wsk_cmd

    @wsk_cmd.setter
    def wsk_cmd(self, wsk_cmd: List[str]):
        self._wsk_cmd = [*wsk_cmd, "action", "invoke", "--result", self.fname]

    @staticmethod
    def get_command(payload: dict) -> List[str]:
        params = []
        for key, value in payload.items():
            params.append("--param")
            params.append(key)
            params.append(json.dumps(value))
        return params

    def sync_invoke(self, payload: dict) -> ExecutionResult:
        command = self.wsk_cmd + self.get_command(payload)
        error = None
        try:
            begin = datetime.datetime.now()
            response = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            end = datetime.datetime.now()
            parsed_response = response.stdout.decode("utf-8")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            end = datetime.datetime.now()
            error = e

        openwhisk_result = ExecutionResult.from_times(begin, end)
        if error is not None:
            self.logging.error("Invocation of {} failed!".format(self.fname))
            openwhisk_result.stats.failure = True
            return openwhisk_result

        return_content = json.loads(parsed_response)
        openwhisk_result.parse_benchmark_output(return_content)
        return openwhisk_result

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:
        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> dict:
        return {"type": "Library", "name": self.fname}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return LibraryTrigger(obj["name"])

    @staticmethod
    def typename() -> str:
        return "OpenWhisk.LibraryTrigger"


class HTTPTrigger(Trigger):
    def __init__(self, fname: str, url: str):
        super().__init__()
        self.fname = fname
        self.url = url

    @staticmethod
    def typename() -> str:
        return "OpenWhisk.HTTPTrigger"

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.HTTP

    def sync_invoke(self, payload: dict) -> ExecutionResult:
        self.logging.debug(f"Invoke function {self.url}")
        return self._http_invoke(payload, self.url, False)

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:
        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> dict:
        return {"type": "HTTP", "fname": self.fname, "url": self.url}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return HTTPTrigger(obj["fname"], obj["url"])
