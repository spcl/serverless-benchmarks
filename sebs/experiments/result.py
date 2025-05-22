from datetime import datetime
from typing import Dict, List, Optional, Tuple  # noqa

from sebs.cache import Cache
from sebs.faas.config import Config as DeploymentConfig
from sebs.faas.function import Function, ExecutionResult
from sebs.utils import LoggingHandlers
from sebs.experiments.config import Config as ExperimentConfig


class Result:
    """
    Represents the results of a SeBS experiment.

    Stores experiment and deployment configurations, invocation details,
    metrics, and timing information.
    """
    def __init__(
        self,
        experiment_config: ExperimentConfig,
        deployment_config: DeploymentConfig,
        invocations: Optional[Dict[str, Dict[str, ExecutionResult]]] = None,
        metrics: Optional[Dict[str, dict]] = None,
        result_bucket: Optional[str] = None,
    ):
        """
        Initialize a new Result object.

        :param experiment_config: The configuration of the experiment.
        :param deployment_config: The configuration of the FaaS deployment.
        :param invocations: Optional dictionary of invocation results, keyed by function name and request ID.
        :param metrics: Optional dictionary of additional metrics, keyed by function name.
        :param result_bucket: Optional name of the bucket where results are stored.
        """
        self.config = {
            "experiments": experiment_config,
            "deployment": deployment_config,
        }
        if not invocations:
            self._invocations = {}
        else:
            self._invocations = invocations
        if not metrics:
            self._metrics = {}
        else:
            self._metrics = metrics
        self.result_bucket = result_bucket
        self.begin_time: Optional[float] = None
        self.end_time: Optional[float] = None

    def begin(self):
        """Records the start time of the experiment."""
        self.begin_time = datetime.now().timestamp()

    def end(self):
        """Records the end time of the experiment."""
        self.end_time = datetime.now().timestamp()

    def times(self) -> Tuple[Optional[float], Optional[float]]:
        """
        Return the begin and end timestamps of the experiment.

        :return: Tuple containing (begin_timestamp, end_timestamp).
                 Timestamps can be None if begin() or end() haven't been called.
        """
        return self.begin_time, self.end_time

    def add_result_bucket(self, result_bucket: str):
        """
        Set the name of the S3/Blob bucket where results are stored.

        :param result_bucket: Name of the bucket.
        """
        self.result_bucket = result_bucket

    def add_invocation(self, func: Function, invocation: ExecutionResult):
        """
        Add an invocation result to this experiment result.

        If the invocation has no request_id (e.g., due to failure), a synthetic
        ID is generated.

        :param func: The Function object that was invoked.
        :param invocation: The ExecutionResult of the invocation.
        """
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
        """
        Return a list of function names for which invocations have been recorded.

        :return: List of function names.
        """
        return list(self._invocations.keys())

    def invocations(self, func: str) -> Dict[str, ExecutionResult]:
        """
        Return all recorded invocations for a specific function.

        :param func: The name of the function.
        :return: Dictionary of ExecutionResult objects, keyed by request ID.
        """
        return self._invocations[func]

    def metrics(self, func: str) -> dict:
        """
        Return or initialize the metrics dictionary for a specific function.

        If no metrics exist for the function, an empty dictionary is created.

        :param func: The name of the function.
        :return: Dictionary of metrics for the function.
        """
        if func not in self._metrics:
            self._metrics[func] = {}
        return self._metrics[func]

    @staticmethod
    def deserialize(cached_config: dict, cache: Cache, handlers: LoggingHandlers) -> "Result":
        """
        Deserialize a Result object from a dictionary (typically from a cache or JSON file).

        Reconstructs ExperimentConfig, DeploymentConfig, and ExecutionResult objects.

        :param cached_config: Dictionary containing serialized Result data.
        :param cache: Cache client instance, used for deserializing DeploymentConfig.
        :param handlers: Logging handlers, used for deserializing DeploymentConfig.
        :return: A new Result instance.
        """
        invocations: Dict[str, dict] = {}
        for func, func_invocations in cached_config["_invocations"].items():
            invocations[func] = {}
            for invoc_id, invoc in func_invocations.items():
                invocations[func][invoc_id] = ExecutionResult.deserialize(invoc)
        ret = Result(
            ExperimentConfig.deserialize(cached_config["config"]["experiments"]),
            DeploymentConfig.deserialize(cached_config["config"]["deployment"], cache, handlers),
            invocations,
            # FIXME: compatibility with old results
            cached_config["metrics"] if "metrics" in cached_config else {},
            cached_config["result_bucket"],
        )
        ret.begin_time = cached_config["begin_time"]
        ret.end_time = cached_config["end_time"]
        return ret
