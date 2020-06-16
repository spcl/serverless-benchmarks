
import logging
import os
from typing import cast


from sebs.cache import Cache
from sebs.faas.config import Config, Credentials, Resources


class AzureCredentials(Credentials):

    _app_id: str
    _tenant: str
    _password: str

    def __init__(self, app_id: str, tenant: str, password: str):
        self._app_id = app_id
        self._tenant = tenant
        self._password = password

    @property
    def app_id(self) -> str:
        return self._app_id

    @property
    def tenant(self) -> str:
        return self._tenant

    @property
    def password(self) -> str:
        return self._password

    @staticmethod
    def deserialize(dct: dict) -> Credentials:
        return AzureCredentials(dct["appId"], dct["tenant"], dct["password"])

    @staticmethod
    def initialize(config: dict, cache: Cache) -> Credentials:

        # FIXME: update return types of both functions to avoid cast
        # needs 3.7+  to support annotations
        cached_config = cache.get_config("azure")
        ret: AzureCredentials
        # Load cached values
        if cached_config and "credentials" in cached_config:
            logging.info("Using cached credentials for Azure")
            ret = cast(
                AzureCredentials, AzureCredentials.deserialize(cached_config["credentials"])
            )
        else:
            logging.info("No cached credentials for Azure found, initialize!")
            # Check for new config
            if "credentials" in config:
                ret = cast(
                    AzureCredentials, AzureCredentials.deserialize(config["credentials"])
                )
            elif "AZURE_SECRET_APPLICATION_ID" in os.environ:
                ret = AzureCredentials(
                    os.environ["AZURE_SECRET_APPLICATION_ID"],
                    os.environ["AZURE_SECRET_TENANT"],
                    os.environ["AZURE_SECRET_PASSWORD"]
                )
            else:
                raise RuntimeError(
                    "Azure login credentials are missing! Please set "
                    "up environmental variables AZURE_SECRET_APPLICATION_ID and "
                    "AZURE_SECRET_TENANT and AZURE_SECRET_PASSWORD"
                )
            cache.update_config(
                val=self.app_id,
                keys=['azure', 'credentials', 'appId']
            )
            cache.update_config(
                val=self.tenant,
                keys=['azure', 'credentials', 'tenant']
            )
            cache.update_config(
                val=self.password,
                keys=['azure', 'credentials', 'password']
            )
        return ret

    def serialize(self) -> dict:
        out = {"appId": self.app_id, "tenant": self.tenant, "password": self.password}
        return out


class AzureResources(Resources):

    resource_group_name = None
    storage_account_name = None
    storage_connection_string = None

    def __init__(self):
        pass

    # FIXME: python3.7+ future annotatons
    @staticmethod
    def deserialize(dct: dict) -> Resources:
        return AzureResources()

    def serialize(self) -> dict:
        return {}

    @staticmethod
    def initialize(config: dict, cache: Cache) -> Resources:

        cached_config = cache.get_config("azure")
        ret: AzureResources
        # Load cached values
        if cached_config and "resources" in cached_config:
            logging.info("Using cached resources for Azure")
            ret = cast(
                AzureResources, AzureResources.deserialize(cached_config["resources"])
            )
        else:
            # Check for new config
            if "resources" in config:
                logging.info(
                    "No cached resources for Azure found, using user configuration."
                )
                ret = cast(AzureResources, AzureResources.deserialize(config["resources"]))
            else:
                logging.info("No resources for AWS found, initialize!")
                ret = AzureResources()

        if not ret.lambda_role:
            # FIXME: hardcoded value for test purposes, add generation here
            ret.lambda_role = "arn:aws:iam::261490803749:role/aws-role-test"
        cache.update_config(
            val=ret.lambda_role, keys=["aws", "resources", "lambda-role"]
        )
        return ret


class AzureConfig(Config):
    def __init__(self, credentials: AzureCredentials, resources: AzureResources):
        self._credentials = credentials
        self._resources = resources

    @property
    def credentials(self) -> AzureCredentials:
        return self._credentials

    @property
    def resources(self) -> AzureResources:
        return self._resources

    # FIXME: use future annotations (see sebs/faas/system)
    @staticmethod
    def deserialize(cfg: Config, dct: dict):
        config = cast(AzureConfig, cfg)

    @staticmethod
    def initialize(config: dict, cache: Cache) -> Config:

        cached_config = cache.get_config("azure")
        # FIXME: use future annotations (see sebs/faas/system)
        credentials = cast(AzureCredentials, AzureCredentials.initialize(config, cache))
        resources = cast(AzureResources, AzureResources.initialize(config, cache))
        config_obj = AWSConfig(credentials, resources)
        # Load cached values
        if cached_config:
            logging.info("Using cached config for Azure")
            AzureConfig.deserialize(config_obj, cached_config)
        else:
            logging.info("Using user-provided config for Azure")
            AzureConfig.deserialize(config_obj, config)

        return config_obj

    def serialize(self) -> dict:
        out = {
            "credentials": self._credentials.serialize(),
            "resources": self._resources.serialize(),
        }
        return out
