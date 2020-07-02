from datetime import datetime
from typing import Dict, Optional, Tuple  # noqa

from sebs.cache import Cache
from sebs.faas.config import Config as DeploymentConfig
from sebs.faas.function import Function, ExecutionResult
from sebs.experiments.config import Config as ExperimentConfig


class Result:
    def __init__(
        self,
        experiment_config: ExperimentConfig,
        deployment_config: DeploymentConfig,
        invocations: Dict[str, Dict[str, ExecutionResult]] = {},
        result_bucket: Optional[str] = None,
    ):
        self.config = {
            "experiments": experiment_config,
            "deployment": deployment_config,
        }
        self._invocations = invocations
        self.result_bucket = result_bucket

    def begin(self):
        self.begin_time = datetime.now().timestamp()

    def end(self):
        self.end_time = datetime.now().timestamp()

    def times(self) -> Tuple[int, int]:
        return self.begin_time, self.end_time

    def add_result_bucket(self, result_bucket: str):
        self.result_bucket = result_bucket

    def add_invocation(self, func: Function, invocation: ExecutionResult):
        if func.name in self._invocations:
            self._invocations.get(func.name)[  # type: ignore
                invocation.request_id
            ] = invocation
        else:
            self._invocations[func.name] = {invocation.request_id: invocation}

    def invocations(self, func: Function) -> Dict[str, ExecutionResult]:
        return self._invocations[func.name]

    @staticmethod
    def deserialize(cached_config: dict, cache: Cache) -> "Result":
        invocations: Dict[str, dict] = {}
        for func, func_invocations in cached_config["_invocations"].items():
            invocations[func] = {}
            for invoc_id, invoc in func_invocations.items():
                invocations[func][invoc_id] = ExecutionResult.deserialize(invoc)
        ret = Result(
            ExperimentConfig.deserialize(cached_config["config"]["experiments"]),
            DeploymentConfig.deserialize(cached_config["config"]["deployment"], cache),
            invocations,
            cached_config["result_bucket"],
        )
        ret.begin_time = cached_config["begin_time"]
        ret.end_time = cached_config["end_time"]
        return ret
