from datetime import datetime
from typing import Dict, List, Optional, Tuple, Union  # noqa

from sebs.cache import Cache
from sebs.faas.config import Config as DeploymentConfig
from sebs.faas.function import Function, ExecutionResult
from sebs.utils import LoggingHandlers
from sebs.experiments.config import Config as ExperimentConfig


class Result:
    def __init__(
        self,
        experiment_config: ExperimentConfig,
        deployment_config: Optional[DeploymentConfig] = None,
        invocations: Optional[Dict[str, Dict[str, ExecutionResult]]] = None,
        metrics: Optional[Dict[str, dict]] = None,
        result_bucket: Optional[str] = None,
    ):
        self.config: Dict[str, Union[ExperimentConfig, DeploymentConfig]] = {
            "experiments": experiment_config
        }
        if deployment_config is not None:
            self.config["deployment"] = deployment_config
        if not invocations:
            self._invocations = {}
        else:
            self._invocations = invocations
        if not metrics:
            self._metrics = {}
        else:
            self._metrics = metrics
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
        # the function has most likely failed, thus no request id
        if invocation.request_id:
            req_id = invocation.request_id
        else:
            req_id = f"failed-{len(self._invocations.get(func.name, []))}"

        if func.name in self._invocations:
            self._invocations.get(func.name)[req_id] = invocation  # type: ignore
        else:
            self._invocations[func.name] = {req_id: invocation}

    def functions(self) -> List[str]:
        return list(self._invocations.keys())

    def invocations(self, func: str) -> Dict[str, ExecutionResult]:
        return self._invocations[func]

    def metrics(self, func: str) -> dict:
        if func not in self._metrics:
            self._metrics[func] = {}
        return self._metrics[func]

    @staticmethod
    def deserialize(
        cached_config: dict, cache: Optional[Cache], handlers: Optional[LoggingHandlers]
    ) -> "Result":
        invocations: Dict[str, dict] = {}
        for func, func_invocations in cached_config["_invocations"].items():
            invocations[func] = {}
            for invoc_id, invoc in func_invocations.items():
                invocations[func][invoc_id] = ExecutionResult.deserialize(invoc)

        deployment_cfg = None
        if cache is not None and handlers is not None:
            deployment_cfg = DeploymentConfig.deserialize(
                cached_config["config"]["deployment"], cache, handlers
            )
        ret = Result(
            ExperimentConfig.deserialize(cached_config["config"]["experiments"]),
            deployment_cfg,
            invocations,
            # FIXME: compatibility with old results
            cached_config["metrics"] if "metrics" in cached_config else {},
            cached_config["result_bucket"],
        )
        ret.begin_time = cached_config["begin_time"]
        ret.end_time = cached_config["end_time"]
        return ret
