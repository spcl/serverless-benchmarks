from typing import cast, Optional, Set

from sebs.cache import Cache
from sebs.faas.config import Config, Credentials, Resources
from sebs.storage.resources import SelfHostedResources
from sebs.storage.config import NoSQLStorageConfig, PersistentStorageConfig
from sebs.utils import LoggingHandlers


class SonataFlowCredentials(Credentials):
    def serialize(self) -> dict:
        return {}

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Credentials:
        return SonataFlowCredentials()


class SonataFlowResources(SelfHostedResources):
    def __init__(
        self,
        storage_cfg: Optional[PersistentStorageConfig] = None,
        nosql_storage_cfg: Optional[NoSQLStorageConfig] = None,
    ):
        super().__init__("sonataflow", storage_cfg, nosql_storage_cfg)
        self._allocated_ports: Set[int] = set()
        self._runtime_url: str = "http://localhost:8080"
        self._endpoint_prefix: str = "services"

    @property
    def allocated_ports(self) -> set:
        return self._allocated_ports

    @property
    def runtime_url(self) -> str:
        return self._runtime_url

    @property
    def endpoint_prefix(self) -> str:
        return self._endpoint_prefix

    def serialize(self) -> dict:
        out = super().serialize()
        out["allocated_ports"] = list(self._allocated_ports)
        out["runtime"] = {
            "url": self._runtime_url,
            "endpoint_prefix": self._endpoint_prefix,
        }
        return out

    @staticmethod
    def _initialize_resources(res: "SonataFlowResources", cfg: dict):
        source = cfg.get("resources", cfg)
        if "allocated_ports" in source:
            res._allocated_ports = set(source["allocated_ports"])
        runtime = source.get("runtime", {})
        res._runtime_url = runtime.get("url", res._runtime_url)
        res._endpoint_prefix = runtime.get("endpoint_prefix", res._endpoint_prefix)

    @staticmethod
    def initialize(res: Resources, config: dict):
        resources = cast(SonataFlowResources, res)
        SonataFlowResources._initialize_resources(resources, config)

    def update_cache(self, cache: Cache):
        super().update_cache(cache)
        cache.update_config(val=list(self._allocated_ports), keys=["sonataflow", "resources", "allocated_ports"])
        cache.update_config(val=self._runtime_url, keys=["sonataflow", "resources", "runtime", "url"])
        cache.update_config(
            val=self._endpoint_prefix,
            keys=["sonataflow", "resources", "runtime", "endpoint_prefix"],
        )

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Resources:
        ret = SonataFlowResources()

        cached_config = cache.get_config("sonataflow")
        ret._deserialize(ret, config, cached_config)

        if "resources" in config:
            ret.load_redis(config["resources"])
        elif cached_config and "resources" in cached_config:
            ret.load_redis(cached_config["resources"])

        if cached_config and "resources" in cached_config:
            SonataFlowResources._initialize_resources(ret, cached_config["resources"])
            ret.logging_handlers = handlers
            ret.logging.info("Using cached resources for SonataFlow")
        else:
            ret.logging_handlers = handlers
            SonataFlowResources._initialize_resources(ret, config)

        return ret


class SonataFlowConfig(Config):
    def __init__(self):
        super().__init__(name="sonataflow")
        self._credentials = SonataFlowCredentials()
        self._resources = SonataFlowResources()

    @staticmethod
    def typename() -> str:
        return "SonataFlow.Config"

    @staticmethod
    def initialize(cfg: Config, dct: dict):
        pass

    @property
    def credentials(self) -> SonataFlowCredentials:
        return self._credentials

    @property
    def resources(self) -> SonataFlowResources:
        return self._resources

    @resources.setter
    def resources(self, val: SonataFlowResources):
        self._resources = val

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Config:
        cfg = SonataFlowConfig()
        cfg.resources = cast(SonataFlowResources, SonataFlowResources.deserialize(config, cache, handlers))
        cfg.logging_handlers = handlers
        return cfg

    def serialize(self) -> dict:
        return {
            "name": "sonataflow",
            "region": self._region,
            "resources": self._resources.serialize(),
        }

    def update_cache(self, cache: Cache):
        self.resources.update_cache(cache)
