from datetime import datetime
from typing import Dict, Optional, Tuple  # noqa

from sebs.faas.config import Config as DeploymentConfig
from sebs.faas.function import Function, ExecutionResult
from sebs.experiments.config import Config as ExperimentConfig


class Result:
    def __init__(
        self, experiment_config: ExperimentConfig, deployment_config: DeploymentConfig
    ):
        self.config = {
            "experiments": experiment_config,
            "deployment": deployment_config,
        }
        self._invocations: Dict[str, Dict[str, ExecutionResult]] = {}
        self.result_bucket: Optional[str] = None

    def begin(self) -> float:
        self.begin_time = datetime.now().timestamp()

    def end(self) -> float:
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
