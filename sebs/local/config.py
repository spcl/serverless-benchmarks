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
    def path(self) -> str:
        return self._path

    @property
    def allocated_ports(self) -> set:
        return self._allocated_ports

    def serialize(self) -> dict:
        out = {
            "allocated_ports": list(self._allocated_ports)
        }
        return out

    @staticmethod
    def initialize(res: Resources, cfg: dict):
        pass

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Resources:
        ret = LocalResources()
        ret._path = config["path"]
        # Check for new config
        if "storage" in config:
            ret._storage = MinioConfig.deserialize(config["storage"])
            ret.logging.info("Using user-provided configuration of storage for local containers.")

        if "allocated_ports" in config:
            ret._allocated_ports = set(config["allocated_ports"])

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
        with open(self.resources.path, "r+") as out:
            config = json.load(out)
            config["deployment"]["local"].update(self.resources.serialize())
            out.seek(0)
            out.write(serialize(config))

        return {}

    def update_cache(self, cache: Cache):
        pass
