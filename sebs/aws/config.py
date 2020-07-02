import logging
import os
from typing import cast


from sebs.cache import Cache
from sebs.faas.config import Config, Credentials, Resources


class AWSCredentials(Credentials):

    _access_key: str
    _secret_key: str

    def __init__(self, access_key: str, secret_key: str):
        self._access_key = access_key
        self._secret_key = secret_key

    @property
    def access_key(self) -> str:
        return self._access_key

    @property
    def secret_key(self) -> str:
        return self._secret_key

    @staticmethod
    def initialize(dct: dict) -> Credentials:
        return AWSCredentials(dct["access_key"], dct["secret_key"])

    @staticmethod
    def deserialize(config: dict, cache: Cache) -> Credentials:

        # FIXME: update return types of both functions to avoid cast
        # needs 3.7+  to support annotations
        cached_config = cache.get_config("aws")
        ret: AWSCredentials
        # Load cached values
        if cached_config and "credentials" in cached_config:
            logging.info("Using cached credentials for AWS")
            ret = cast(
                AWSCredentials, AWSCredentials.initialize(cached_config["credentials"])
            )
        else:
            logging.info("No cached credentials for AWS found, initialize!")
            # Check for new config
            if "credentials" in config:
                ret = cast(
                    AWSCredentials, AWSCredentials.initialize(config["credentials"])
                )
            elif "AWS_ACCESS_KEY_ID" in os.environ:
                ret = AWSCredentials(
                    os.environ["AWS_ACCESS_KEY_ID"], os.environ["AWS_SECRET_ACCESS_KEY"]
                )
            else:
                raise RuntimeError(
                    "AWS login credentials are missing! Please set "
                    "up environmental variables AWS_ACCESS_KEY_ID and "
                    "AWS_SECRET_ACCESS_KEY"
                )
            cache.update_config(
                val=ret.access_key, keys=["aws", "credentials", "access_key"]
            )
            cache.update_config(
                val=ret.secret_key, keys=["aws", "credentials", "secret_key"]
            )
        return ret

    def serialize(self) -> dict:
        out = {"access_key": self.access_key, "secret_key": self.secret_key}
        return out


class AWSResources(Resources):
    def __init__(self, lambda_role: str):
        self._lambda_role = lambda_role

    @property
    def lambda_role(self):
        return self._lambda_role

    @lambda_role.setter
    def lambda_role(self, val):
        self._lambda_role = val

    # FIXME: python3.7+ future annotatons
    @staticmethod
    def initialize(dct: dict) -> Resources:
        return AWSResources(dct["lambda-role"] if "lambda-role" in dct else "")

    def serialize(self) -> dict:
        out = {"lambda-role": self._lambda_role}
        return out

    @staticmethod
    def deserialize(config: dict, cache: Cache) -> Resources:

        cached_config = cache.get_config("aws")
        ret: AWSResources
        # Load cached values
        if cached_config and "resources" in cached_config:
            logging.info("Using cached resources for AWS")
            ret = cast(
                AWSResources, AWSResources.initialize(cached_config["resources"])
            )
        else:
            # Check for new config
            if "resources" in config:
                logging.info(
                    "No cached resources for AWS found, using user configuration."
                )
                ret = cast(AWSResources, AWSResources.initialize(config["resources"]))
            else:
                logging.info("No resources for AWS found, initialize!")
                ret = AWSResources(lambda_role="")

        if not ret.lambda_role:
            # FIXME: hardcoded value for test purposes, add generation here
            ret.lambda_role = "arn:aws:iam::261490803749:role/aws-role-test"
        cache.update_config(
            val=ret.lambda_role, keys=["aws", "resources", "lambda-role"]
        )
        return ret


class AWSConfig(Config):
    def __init__(self, credentials: AWSCredentials, resources: AWSResources):
        self._credentials = credentials
        self._resources = resources

    @property
    def credentials(self) -> AWSCredentials:
        return self._credentials

    @property
    def resources(self) -> AWSResources:
        return self._resources

    # FIXME: use future annotations (see sebs/faas/system)
    @staticmethod
    def initialize(cfg: Config, dct: dict):
        config = cast(AWSConfig, cfg)
        config._region = dct["region"]

    @staticmethod
    def deserialize(config: dict, cache: Cache) -> Config:

        cached_config = cache.get_config("aws")
        # FIXME: use future annotations (see sebs/faas/system)
        credentials = cast(AWSCredentials, AWSCredentials.deserialize(config, cache))
        resources = cast(AWSResources, AWSResources.deserialize(config, cache))
        config_obj = AWSConfig(credentials, resources)
        # Load cached values
        if cached_config:
            logging.info("Using cached config for AWS")
            AWSConfig.initialize(config_obj, cached_config)
        else:
            logging.info("Using user-provided config for AWS")
            AWSConfig.initialize(config_obj, config)
            cache.update_config(val=config_obj.region, keys=["aws", "region"])

        return config_obj

    def serialize(self) -> dict:
        out = {
            "name": "aws",
            "region": self._region,
            "credentials": self._credentials.serialize(),
            "resources": self._resources.serialize(),
        }
        return out
