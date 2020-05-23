from .aws.aws import AWS, AWSConfig  # noqa

from .cache import Cache  # noqa
from .benchmark import Benchmark  # noqa
from .experiments.config import Config as ExperimentConfig


def get_deployment(cache_client: Cache, config: dict):

    implementations = {"aws": AWS}
    configs = {"aws": AWSConfig.initialize}
    name = config["name"]
    if name not in implementations:
        raise RuntimeError("Deployment {name} not supported!".format(**config))

    # FIXME: future annotations, requires Python 3.7+
    deployment_config = configs[name](config, cache_client)
    deployment_client = implementations[name](
        deployment_config, cache_client  # type: ignore
    )
    return deployment_client


def get_experiment(config: dict) -> ExperimentConfig:

    experiment_config = ExperimentConfig.deserialize(config)
    return experiment_config
