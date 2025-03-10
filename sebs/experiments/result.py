"""Experiment result collection and management.

This module provides the Result class for managing experiment results, including:
- Function invocation results
- Metrics from cloud providers
- Experiment start and end times
- Configuration information

The Result class handles serialization, deserialization, and analysis of
experiment results, making it easier to process and visualize the data.
"""

from datetime import datetime
from typing import Dict, List, Optional, Tuple  # noqa

from sebs.cache import Cache
from sebs.faas.config import Config as DeploymentConfig
from sebs.faas.function import Function, ExecutionResult
from sebs.utils import LoggingHandlers
from sebs.experiments.config import Config as ExperimentConfig


class Result:
    """Experiment result collection and management.
    
    This class stores and manages the results of experiments, including function
    invocation results, metrics from cloud providers, and configuration information.
    It provides methods for adding invocation results, retrieving metrics, and
    serializing/deserializing results.
    
    Attributes:
        config: Dictionary containing experiment and deployment configurations
        _invocations: Dictionary mapping function names to invocation results
        _metrics: Dictionary mapping function names to metrics
        _start_time: Experiment start time
        _end_time: Experiment end time
        result_bucket: Optional bucket name for storing results
        logging_handlers: Logging handlers for the result
    """
    
    def __init__(
        self,
        experiment_config: ExperimentConfig,
        deployment_config: DeploymentConfig,
        invocations: Optional[Dict[str, Dict[str, ExecutionResult]]] = None,
        metrics: Optional[Dict[str, dict]] = None,
        result_bucket: Optional[str] = None,
    ):
        """Initialize a new experiment result.
        
        Args:
            experiment_config: Experiment configuration
            deployment_config: Deployment configuration
            invocations: Optional dictionary of function invocation results
            metrics: Optional dictionary of function metrics
            result_bucket: Optional bucket name for storing results
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

    def begin(self):
        """Mark the beginning of the experiment.
        
        This method records the start time of the experiment.
        """
        self.begin_time = datetime.now().timestamp()

    def end(self):
        """Mark the end of the experiment.
        
        This method records the end time of the experiment.
        """
        self.end_time = datetime.now().timestamp()

    def times(self) -> Tuple[int, int]:
        """Get the start and end times of the experiment.
        
        Returns:
            Tuple of (start_time, end_time) as Unix timestamps
        """
        return self.begin_time, self.end_time

    def add_result_bucket(self, result_bucket: str):
        """Set the result bucket for storing experiment results.
        
        Args:
            result_bucket: Name of the bucket to store results in
        """
        self.result_bucket = result_bucket

    def add_invocation(self, func: Function, invocation: ExecutionResult):
        """Add an invocation result for a specific function.
        
        If the invocation doesn't have a request ID (likely due to failure),
        a synthetic ID is generated.
        
        Args:
            func: Function the invocation belongs to
            invocation: Execution result to add
        """
        # The function has most likely failed, thus no request id
        if invocation.request_id:
            req_id = invocation.request_id
        else:
            req_id = f"failed-{len(self._invocations.get(func.name, []))}"

        # Add to existing invocations or create new entry
        if func.name in self._invocations:
            self._invocations.get(func.name)[req_id] = invocation  # type: ignore
        else:
            self._invocations[func.name] = {req_id: invocation}

    def functions(self) -> List[str]:
        """Get a list of all function names in the results.
        
        Returns:
            List of function names
        """
        return list(self._invocations.keys())

    def invocations(self, func: str) -> Dict[str, ExecutionResult]:
        """Get invocation results for a specific function.
        
        Args:
            func: Name of the function to get invocation results for
            
        Returns:
            Dictionary mapping request IDs to execution results
            
        Raises:
            KeyError: If function name is not found in results
        """
        return self._invocations[func]

    def metrics(self, func: str) -> dict:
        """Get metrics for a specific function.
        
        If no metrics exist for the function, an empty dictionary is created
        and returned.
        
        Args:
            func: Name of the function to get metrics for
            
        Returns:
            Dictionary of metrics for the function
        """
        if func not in self._metrics:
            self._metrics[func] = {}
        return self._metrics[func]

    @staticmethod
    def deserialize(cached_config: dict, cache: Cache, handlers: LoggingHandlers) -> "Result":
        """Deserialize a result from a dictionary representation.
        
        This static method creates a new Result object from a dictionary
        representation, which may have been loaded from a file or cache.
        
        Args:
            cached_config: Dictionary representation of the result
            cache: Cache instance for resolving references
            handlers: Logging handlers for the result
            
        Returns:
            A new Result object with settings from the dictionary
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
