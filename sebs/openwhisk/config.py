from sebs.cache import Cache
from sebs.faas.config import Credentials, Resources, Config
from sebs.utils import LoggingHandlers

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
    ):
        super().__init__()
        self._docker_registry = registry if registry != "" else None
        self._docker_username = username if username != "" else None
        self._docker_password = password if password != "" else None

    @staticmethod
    def typename() -> str:
        return "OpenWhisk.Credentials"

    @property
    def docker_registry(self) -> Optional[str]:
        return self._docker_registry

    @property
    def docker_username(self) -> Optional[str]:
        return self._docker_username

    @property
    def docker_password(self) -> Optional[str]:
        return self._docker_password

    @staticmethod
    def initialize(dct: dict) -> Resources:
        return OpenWhiskResources(dct["registry"], dct["username"], dct["password"])

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Resources:

        cached_config = cache.get_config("openwhisk")
        ret: OpenWhiskResources
        # Check for new config
        if "docker_registry" in config:
            ret = cast(OpenWhiskResources, OpenWhiskResources.initialize(config["docker_registry"]))
            ret.logging.info("Using user-provided Docker registry for OpenWhisk.")
            ret.logging_handlers = handlers
        # Load cached values
        elif (
            cached_config
            and "resources" in cached_config
            and "docker" in cached_config["resources"]
        ):
            ret = cast(
                OpenWhiskResources,
                OpenWhiskResources.initialize(cached_config["resources"]["docker"]),
            )
            ret.logging_handlers = handlers
            ret.logging.info("Using cached Docker registry for OpenWhisk")
        else:
            ret = OpenWhiskResources()
            ret.logging.info("Using default Docker registry for OpenWhisk.")
            ret.logging_handlers = handlers

        return ret

    def update_cache(self, cache: Cache):
        cache.update_config(
            val=self.docker_registry, keys=["openwhisk", "resources", "docker", "registry"]
        )
        cache.update_config(
            val=self.docker_username, keys=["openwhisk", "resources", "docker", "username"]
        )
        cache.update_config(
            val=self.docker_password, keys=["openwhisk", "resources", "docker", "password"]
        )

    def serialize(self) -> dict:
        out = {
            "docker_registry": self.docker_registry,
            "docker_username": self.docker_username,
            "docker_password": self.docker_password,
        }
        return out


class OpenWhiskConfig(Config):
    name: str
    shutdownStorage: bool
    cache: Cache

    def __init__(self, config: dict, cache: Cache):
        super().__init__()
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
