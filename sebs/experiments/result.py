from datetime import datetime
from typing import Dict, Optional

from sebs.faas.config import Config as DeploymentConfig
from sebs.faas.function import ExecutionResult
from sebs.experiments.config import Config as ExperimentConfig


class Result:
    def __init__(
        self, experiment_config: ExperimentConfig, deployment_config: DeploymentConfig
    ):
        self.config = {
            "experiments": experiment_config,
            "deployment": deployment_config,
        }
        self.invocations: Dict[str, Dict[str, ExecutionResult]] = {}
        self.result_bucket: Optional[str] = None

    def begin(self):
        self.begin_time = datetime.now().timestamp()

    def end(self):
        self.end_time = datetime.now().timestamp()

    def add_result_bucket(self, result_bucket: str):
        self.result_bucket = result_bucket

    def add_invocation(self, func_name: str, invocation: ExecutionResult):
        if func_name in self.invocations:
            self.invocations.get(func_name)[  # type: ignore
                invocation.request_id
            ] = invocation
        else:
            self.invocations[func_name] = {invocation.request_id: invocation}
