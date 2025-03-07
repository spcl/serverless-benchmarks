from typing import cast, Optional, Set

from sebs.cache import Cache
from sebs.faas.config import Config, Credentials, Resources
from sebs.storage.resources import SelfHostedResources
from sebs.storage.config import NoSQLStorageConfig, PersistentStorageConfig
from sebs.utils import LoggingHandlers


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


class LocalResources(SelfHostedResources):
    def __init__(
        self,
        storage_cfg: Optional[PersistentStorageConfig] = None,
        nosql_storage_cfg: Optional[NoSQLStorageConfig] = None,
    ):
        self._path: str = ""
        super().__init__("local", storage_cfg, nosql_storage_cfg)
        self._allocated_ports: Set[int] = set()

    @property
    def allocated_ports(self) -> set:
        return self._allocated_ports

    def serialize(self) -> dict:
        out = super().serialize()

        out["allocated_ports"] = list(self._allocated_ports)
        return out

    @staticmethod
    def initialize(res: Resources, config: dict):

        resources = cast(LocalResources, res)

        if "allocated_ports" in config:
            resources._allocated_ports = set(config["allocated_ports"])

    def update_cache(self, cache: Cache):
        super().update_cache(cache)
        cache.update_config(
            val=list(self._allocated_ports), keys=["local", "resources", "allocated_ports"]
        )

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Resources:
        ret = LocalResources()

        cached_config = cache.get_config("local")
        ret._deserialize(ret, config, cached_config)

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
        out = {"name": "local", "region": self._region, "resources": self._resources.serialize()}
        return out

    def update_cache(self, cache: Cache):
        self.resources.update_cache(cache)
