from typing import Optional, Dict

import docker

from sebs.aws import AWS, AWSConfig
from sebs.azure.azure import Azure, AzureConfig
from sebs.cache import Cache
from sebs.config import SeBSConfig
from sebs.benchmark import Benchmark
from sebs.faas.system import System as FaasSystem
from sebs.utils import LoggingHandlers

# from sebs.experiments.experiment import Experiment
from sebs.experiments.config import Config as ExperimentConfig


class SeBS:
    @property
    def cache_client(self) -> Cache:
        return self._cache_client

    @property
    def docker_client(self) -> docker.client:
        return self._docker_client

    def logging_handlers(
        self, logging_filename: Optional[str] = None
    ) -> LoggingHandlers:
        if logging_filename in self._logging_handlers:
            return self._logging_handlers[logging_filename]
        else:
            handlers = LoggingHandlers(filename=logging_filename)
            self._logging_handlers[logging_filename] = handlers
            return handlers

    def __init__(self, cache_dir: str):
        self._cache_client = Cache(cache_dir)
        self._docker_client = docker.from_env()
        self._config = SeBSConfig()
        self._logging_handlers: Dict[Optional[str], LoggingHandlers] = {}

    def get_deployment(
        self, config: dict, logging_filename: Optional[str] = None
    ) -> FaasSystem:

        implementations = {"aws": AWS, "azure": Azure}
        configs = {"aws": AWSConfig.deserialize, "azure": AzureConfig.deserialize}
        if name not in implementations:
            raise RuntimeError("Deployment {name} not supported!".format(name=name))

        # FIXME: future annotations, requires Python 3.7+
        handlers = self.logging_handlers(logging_filename)
        deployment_config = configs[name](config, self.cache_client, handlers)
        deployment_client = implementations[name](
            self._config,
            deployment_config,  # type: ignore
            self.cache_client,
            self.docker_client,
            handlers,
        )
        return deployment_client

    def get_experiment(self, config: dict) -> ExperimentConfig:

        experiment_config = ExperimentConfig.deserialize(config)
        return experiment_config
        # implementations = {"perfcost": PerfCost}
        # return implementations[config["type"]](config)

    def get_benchmark(
        self,
        name: str,
        output_dir: str,
        deployment: FaasSystem,
        config: ExperimentConfig,
        logging_filename: Optional[str] = None,
    ) -> Benchmark:
        benchmark = Benchmark(
            name,
            deployment.name(),
            config,
            self._config,
            output_dir,
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
