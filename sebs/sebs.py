from typing import Optional, Dict

import docker

from sebs.aws import AWS
from sebs.azure.azure import Azure
from sebs.cache import Cache
from sebs.config import SeBSConfig
from sebs.benchmark import Benchmark
from sebs.faas.system import System as FaaSSystem
from sebs.faas.config import Config
from sebs.utils import LoggingHandlers

from sebs.experiments.config import Config as ExperimentConfig
from sebs.experiments import (
    Experiment,
    PerfCost,
    NetworkPingPong,
    StartupTime,
    EvictionModel,
)

class SeBS:
    @property
    def cache_client(self) -> Cache:
        return self._cache_client

    @property
    def docker_client(self) -> docker.client:
        return self._docker_client

    @property
    def output_dir(self) -> str:
        return self._output_dir

    def logging_handlers(
        self, logging_filename: Optional[str] = None
    ) -> LoggingHandlers:
        if logging_filename in self._logging_handlers:
            return self._logging_handlers[logging_filename]
        else:
            handlers = LoggingHandlers(filename=logging_filename)
            self._logging_handlers[logging_filename] = handlers
            return handlers

    def __init__(self, cache_dir: str, output_dir: str):
        self._cache_client = Cache(cache_dir)
        self._docker_client = docker.from_env()
        self._config = SeBSConfig()
        self._output_dir = output_dir
        self._logging_handlers: Dict[Optional[str], LoggingHandlers] = {}

    def get_deployment(
        self, config: dict, logging_filename: Optional[str] = None
    ) -> FaaSSystem:

        name = config["name"]
        implementations = {"aws": AWS, "azure": Azure}
        if name not in implementations:
            raise RuntimeError("Deployment {name} not supported!".format(name=name))

        # FIXME: future annotations, requires Python 3.7+
        handlers = self.logging_handlers(logging_filename)
        deployment_config = Config.deserialize(config, self.cache_client, handlers)
        deployment_client = implementations[name](
            self._config,
            deployment_config,  # type: ignore
            self.cache_client,
            self.docker_client,
            handlers,
        )
        return deployment_client

    def get_experiment_config(self, config: dict) -> ExperimentConfig:
        return ExperimentConfig.deserialize(config)

    def get_experiment(
        self, experiment_type: str, config: dict, logging_filename: Optional[str] = None
    ) -> Experiment:
        from sebs.experiments import (
            Experiment,
            PerfCost,
            NetworkPingPong,
            InvocationOverhead,
            EvictionModel
        )
        implementations = {
            "perf-cost": PerfCost,
            "network-ping-pong": NetworkPingPong,
            "invocation-overhead": InvocationOverhead,
            "eviction-model": EvictionModel
        }
        experiment = implementations[experiment_type](self.get_experiment_config(config))
        experiment.logging_handlers = self.logging_handlers(logging_filename)
        return experiment

    def get_benchmark(
        self,
        name: str,
        deployment: FaaSSystem,
        config: ExperimentConfig,
        logging_filename: Optional[str] = None,
    ) -> Benchmark:
        benchmark = Benchmark(
            name,
            deployment.name(),
            config,
            self._config,
            self._output_dir,
            self.cache_client,
            self.docker_client,
        )
        benchmark.logging_handlers = self.logging_handlers(logging_filename)
        return benchmark

    def shutdown(self):
        self.cache_client.shutdown()

    def __enter__(self):
        return self

    def __exit__(self):
        self.shutdown()
