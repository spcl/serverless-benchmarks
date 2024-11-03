import json

from typing import cast, Optional

from sebs.cache import Cache
from sebs.faas.config import Config, Credentials, Resources
from sebs.storage.minio import MinioConfig
from sebs.utils import serialize, LoggingHandlers


class LocalCredentials(Credentials):
    def serialize(self) -> dict:
        return {}

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Credentials:
        return LocalCredentials()


"""
    No need to cache and store - we prepare the benchmark and finish.
    The rest is used later by the user.
"""


class LocalResources(Resources):
    def __init__(self, storage_cfg: Optional[MinioConfig] = None):
        self._path: str = ""
        super().__init__(name="local")
        self._storage = storage_cfg
        self._allocated_ports = set()

    @property
    def storage_config(self) -> Optional[MinioConfig]:
        return self._storage

    @property
    def allocated_ports(self) -> set:
        return self._allocated_ports

    def serialize(self) -> dict:
        out = {
            "allocated_ports": list(self._allocated_ports),
            "storage": self._storage.serialize()
        }
        return out

    @staticmethod
    def initialize(res: Resources, config: dict):

        # Check for new config
        if "storage" in config:
            res._storage = MinioConfig.deserialize(config["storage"])
            res.logging.info("Using user-provided configuration of storage for local containers.")

        if "allocated_ports" in config:
            res._allocated_ports = set(config["allocated_ports"])

    def update_cache(self, cache: Cache):
        super().update_cache(cache)
        cache.update_config(val=list(self._allocated_ports), keys=["local", "resources", "allocated_ports"])
        self._storage.update_cache(["local", "resources", "storage"], cache)

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Resources:
        ret = LocalResources()

        cached_config = cache.get_config("local")
        # Load cached values
        if cached_config and "resources" in cached_config:
            LocalResources.initialize(ret, cached_config["resources"])
            ret.logging_handlers = handlers
            ret.logging.info("Using cached resources for Local")
        else:
            # Check for new config
            ret.logging_handlers = handlers
            LocalResources.initialize(ret, config)

        return ret


class LocalConfig(Config):
    def __init__(self):
        super().__init__(name="local")
        self._credentials = LocalCredentials()
        self._resources = LocalResources()

    @staticmethod
    def typename() -> str:
        return "Local.Config"

    @staticmethod
    def initialize(cfg: Config, dct: dict):
        pass

    @property
    def credentials(self) -> LocalCredentials:
        return self._credentials

    @property
    def resources(self) -> LocalResources:
        return self._resources

    @resources.setter
    def resources(self, val: LocalResources):
        self._resources = val

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Config:

        config_obj = LocalConfig()
        config_obj.resources = cast(
            LocalResources, LocalResources.deserialize(config, cache, handlers)
        )
        config_obj.logging_handlers = handlers
        return config_obj

    def serialize(self) -> dict:
        out = {
            "name": "local",
            "region": self._region,
            "resources": self._resources.serialize()
        }
        return out

    def update_cache(self, cache: Cache):
        self.resources.update_cache(cache)
