from typing import Optional

import docker

from sebs.aws.aws import AWS, AWSConfig
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

    def __init__(self, cache_dir: str):
        self._cache_client = Cache(cache_dir)
        self._docker_client = docker.from_env()
        self._config = SeBSConfig()

    def get_deployment(
        self, config: dict, logging_filename: Optional[str]
    ) -> FaasSystem:

        implementations = {"aws": AWS}
        configs = {"aws": AWSConfig.initialize}
        name = config["name"]
        if name not in implementations:
            raise RuntimeError("Deployment {name} not supported!".format(**config))

        handlers = LoggingHandlers(filename=logging_filename)
        # FIXME: future annotations, requires Python 3.7+
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
        return benchmark

    def shutdown(self):
        self.cache_client.shutdown()

    def __enter__(self):
        return self

    def __exit__(self):
        self.shutdown()
