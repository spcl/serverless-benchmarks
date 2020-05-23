from .aws.aws import AWS, AWSConfig  # noqa

from .cache import Cache  # noqa
from .benchmark import Benchmark  # noqa


def get_deployment(cache_client: Cache, config: dict, language: str):

    implementations = {"aws": AWS}
    configs = {"aws": AWSConfig.initialize}
    name = config["name"]
    if name not in implementations:
        raise RuntimeError("Deployment {name} not supported!".format(**config))

    # FIXME: future annotations, requires Python 3.7+
    deployment_config = configs[name](config, cache_client)
    deployment_client = implementations[name](
        deployment_config, cache_client, language  # type: ignore
    )
    return deployment_client
