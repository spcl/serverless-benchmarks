from __future__ import annotations

from sebs.cache import Cache
from sebs.faas.config import Credentials, Resources, Config
from sebs.utils import LoggingHandlers
from sebs.storage.config import MinioConfig

from typing import cast, Optional


class OpenWhiskCredentials(Credentials):
    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Credentials:
        return OpenWhiskCredentials()

    def serialize(self) -> dict:
        return {}


class OpenWhiskResources(Resources):
    def __init__(
        self,
        registry: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        registry_updated: bool = False,
    ):
        super().__init__(name="openwhisk")
        self._docker_registry = registry if registry != "" else None
        self._docker_username = username if username != "" else None
        self._docker_password = password if password != "" else None
        self._registry_updated = registry_updated
        self._storage: Optional[MinioConfig] = None
        self._storage_updated = False

    @staticmethod
    def typename() -> str:
        return "OpenWhisk.Resources"

    @property
    def docker_registry(self) -> Optional[str]:
        return self._docker_registry

    @property
    def docker_username(self) -> Optional[str]:
        return self._docker_username

    @property
    def docker_password(self) -> Optional[str]:
        return self._docker_password

    @property
    def storage_config(self) -> Optional[MinioConfig]:
        return self._storage

    @property
    def storage_updated(self) -> bool:
        return self._storage_updated

    @property
    def registry_updated(self) -> bool:
        return self._registry_updated

    @staticmethod
    def initialize(res: Resources, dct: dict):
        ret = cast(OpenWhiskResources, res)
        ret._docker_registry = dct["registry"]
        ret._docker_username = dct["username"]
        ret._docker_password = dct["password"]

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Resources:

        cached_config = cache.get_config("openwhisk")
        ret = OpenWhiskResources()
        if cached_config:
            super(OpenWhiskResources, OpenWhiskResources).initialize(
                ret, cached_config["resources"]
            )

        # Check for new config - overrides but check if it's different
        if "docker_registry" in config:

            OpenWhiskResources.initialize(ret, config["docker_registry"])
            ret.logging.info("Using user-provided Docker registry for OpenWhisk.")
            ret.logging_handlers = handlers

            # check if there has been an update
            if not (
                cached_config
                and "resources" in cached_config
                and "docker" in cached_config["resources"]
                and cached_config["resources"]["docker"] == config["docker_registry"]
            ):
                ret._registry_updated = True

        # Load cached values
        elif (
            cached_config
            and "resources" in cached_config
            and "docker" in cached_config["resources"]
        ):
            OpenWhiskResources.initialize(ret, cached_config["resources"]["docker"])
            ret.logging_handlers = handlers
            ret.logging.info("Using cached Docker registry for OpenWhisk")
        else:
            ret = OpenWhiskResources()
            ret.logging.info("Using default Docker registry for OpenWhisk.")
            ret.logging_handlers = handlers
            ret._registry_updated = True

        # Check for new config
        if "storage" in config:
            ret._storage = MinioConfig.deserialize(config["storage"])
            ret.logging.info("Using user-provided configuration of storage for OpenWhisk.")

            # check if there has been an update
            if not (
                cached_config
                and "resources" in cached_config
                and "storage" in cached_config["resources"]
                and cached_config["resources"]["storage"] == config["storage"]
            ):
                ret.logging.info(
                    "User-provided configuration is different from cached storage, "
                    "we will update existing OpenWhisk actions."
                )
                ret._storage_updated = True

        # Load cached values
        elif (
            cached_config
            and "resources" in cached_config
            and "storage" in cached_config["resources"]
        ):
            ret._storage = MinioConfig.deserialize(cached_config["resources"]["storage"])
            ret.logging.info("Using cached configuration of storage for OpenWhisk.")

        return ret

    def update_cache(self, cache: Cache):
        super().update_cache(cache)
        cache.update_config(
            val=self.docker_registry, keys=["openwhisk", "resources", "docker", "registry"]
        )
        cache.update_config(
            val=self.docker_username, keys=["openwhisk", "resources", "docker", "username"]
        )
        cache.update_config(
            val=self.docker_password, keys=["openwhisk", "resources", "docker", "password"]
        )
        if self._storage:
            self._storage.update_cache(["openwhisk", "resources", "storage"], cache)

    def serialize(self) -> dict:
        out: dict = {
            **super().serialize(),
            "docker_registry": self.docker_registry,
            "docker_username": self.docker_username,
            "docker_password": self.docker_password,
        }
        if self._storage:
            out = {**out, "storage": self._storage.serialize()}
        return out


class OpenWhiskConfig(Config):
    name: str
    shutdownStorage: bool
    cache: Cache

    def __init__(self, config: dict, cache: Cache):
        super().__init__(name="openwhisk")
        self._credentials = OpenWhiskCredentials()
        self._resources = OpenWhiskResources()
        self.shutdownStorage = config["shutdownStorage"]
        self.removeCluster = config["removeCluster"]
        self.wsk_exec = config["wskExec"]
        self.wsk_bypass_security = config["wskBypassSecurity"]
        self.experimentalManifest = config["experimentalManifest"]
        self.cache = cache

    @property
    def credentials(self) -> OpenWhiskCredentials:
        return self._credentials

    @property
    def resources(self) -> OpenWhiskResources:
        return self._resources

    @staticmethod
    def initialize(cfg: Config, dct: dict):
        pass

    def serialize(self) -> dict:
        return {
            "name": "openwhisk",
            "shutdownStorage": self.shutdownStorage,
            "removeCluster": self.removeCluster,
            "wskExec": self.wsk_exec,
            "wskBypassSecurity": self.wsk_bypass_security,
            "experimentalManifest": self.experimentalManifest,
            "credentials": self._credentials.serialize(),
            "resources": self._resources.serialize(),
        }

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Config:
        cached_config = cache.get_config("openwhisk")
        resources = cast(
            OpenWhiskResources, OpenWhiskResources.deserialize(config, cache, handlers)
        )

        res = OpenWhiskConfig(config, cached_config)
        res.logging_handlers = handlers
        res._resources = resources
        return res

    def update_cache(self, cache: Cache):
        cache.update_config(val=self.shutdownStorage, keys=["openwhisk", "shutdownStorage"])
        cache.update_config(val=self.removeCluster, keys=["openwhisk", "removeCluster"])
        cache.update_config(val=self.wsk_exec, keys=["openwhisk", "wskExec"])
        cache.update_config(val=self.wsk_bypass_security, keys=["openwhisk", "wskBypassSecurity"])
        cache.update_config(
            val=self.experimentalManifest, keys=["openwhisk", "experimentalManifest"]
        )
        self.resources.update_cache(cache)
