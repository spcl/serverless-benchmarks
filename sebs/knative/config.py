from sebs.cache import Cache
from sebs.faas.config import Resources, Config, Credentials
from sebs.utils import LoggingHandlers
from sebs.storage.config import MinioConfig

from typing import cast, Optional


class KnativeCredentials(Credentials):
    def __init__(self, config: dict):
        super().__init__()
        self._docker_username = config.get("docker_username")
        self._docker_password = config.get("docker_password")

    @staticmethod
    def deserialize(
        config: dict, cache: Cache, handlers: LoggingHandlers
    ) -> "KnativeCredentials":
        cached_config = cache.get_config("knative")
        if cached_config and "credentials" in cached_config:
            return KnativeCredentials(cached_config["credentials"])
        else:
            return KnativeCredentials(config)

    def serialize(self) -> dict:
        return {
            "docker_username": self._docker_username,
            "docker_password": self._docker_password,
        }


class KnativeResources(Resources):
    def __init__(
        self,
        registry: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        registry_updated: bool = False,
    ):
        super().__init__(name="knative")
        self._docker_registry = registry if registry != "" else None
        self._docker_username = username if username != "" else None
        self._docker_password = password if password != "" else None
        self._registry_updated = registry_updated
        self._storage: Optional[MinioConfig] = None
        self._storage_updated = False

    @staticmethod
    def typename() -> str:
        return "Knative.Resources"

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
        ret = cast(KnativeResources, res)
        ret._docker_registry = dct.get("registry")
        ret._docker_username = dct.get("username")
        ret._docker_password = dct.get("password")

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Resources:
        cached_config = cache.get_config("knative")
        ret = KnativeResources()
        if cached_config:
            super(KnativeResources, KnativeResources).initialize(
                ret, cached_config["resources"]
            )

        if "docker_registry" in config:
            KnativeResources.initialize(ret, config["docker_registry"])
            ret.logging.info("Using user-provided Docker registry for Knative.")
            ret.logging_handlers = handlers

            if not (
                cached_config
                and "resources" in cached_config
                and "docker" in cached_config["resources"]
                and cached_config["resources"]["docker"] == config["docker_registry"]
            ):
                ret._registry_updated = True

        elif (
            cached_config
            and "resources" in cached_config
            and "docker" in cached_config["resources"]
        ):
            KnativeResources.initialize(ret, cached_config["resources"]["docker"])
            ret.logging_handlers = handlers
            ret.logging.info("Using cached Docker registry for Knative")
        else:
            ret = KnativeResources()
            ret.logging.info("Using default Docker registry for Knative.")
            ret.logging_handlers = handlers
            ret._registry_updated = True

        if "storage" in config:
            ret._storage = MinioConfig.deserialize(config["storage"])
            ret.logging.info(
                "Using user-provided configuration of storage for Knative."
            )

            if not (
                cached_config
                and "resources" in cached_config
                and "storage" in cached_config["resources"]
                and cached_config["resources"]["storage"] == config["storage"]
            ):
                ret.logging.info(
                    "User-provided configuration is different from cached storage, "
                    "we will update existing Knative function."
                )
                ret._storage_updated = True

        elif (
            cached_config
            and "resources" in cached_config
            and "storage" in cached_config["resources"]
        ):
            ret._storage = MinioConfig.deserialize(
                cached_config["resources"]["storage"]
            )
            ret.logging.info("Using cached configuration of storage for Knative.")

        return ret

    def update_cache(self, cache: Cache):
        super().update_cache(cache)
        cache.update_config(
            val=self.docker_registry,
            keys=["knative", "resources", "docker", "registry"],
        )
        cache.update_config(
            val=self.docker_username,
            keys=["knative", "resources", "docker", "username"],
        )
        cache.update_config(
            val=self.docker_password,
            keys=["knative", "resources", "docker", "password"],
        )
        if self._storage:
            self._storage.update_cache(["knative", "resources", "storage"], cache)

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


class KnativeConfig(Config):
    name: str
    cache: Cache

    def __init__(self, config: dict, cache: Cache):
        super().__init__(name="knative")
        self._resources = KnativeResources()
        self._credentials = KnativeCredentials(config)
        self.knative_exec = config["knativeExec"]
        self.shutdownStorage = config["shutdownStorage"]
        self.removeCluster = config["removeCluster"]
        self.cache = cache

    @property
    def resources(self) -> KnativeResources:
        return self._resources

    @property
    def credentials(self) -> KnativeCredentials:
        return self._credentials

    @staticmethod
    def initialize(cfg: Config, dct: dict):
        pass

    def serialize(self) -> dict:
        return {
            "name": "knative",
            "shutdownStorage": self.shutdownStorage,
            "removeCluster": self.removeCluster,
            "knativeExec": self.knative_exec,
            "resources": self._resources.serialize(),
            "credentials": self._credentials.serialize(),
        }

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Config:
        cached_config = cache.get_config("knative")
        resources = cast(
            KnativeResources, KnativeResources.deserialize(config, cache, handlers)
        )

        res = KnativeConfig(config, cache)
        res.logging_handlers = handlers
        res._resources = resources
        res._credentials = KnativeCredentials.deserialize(config, cache, handlers)
        return res

    def update_cache(self, cache: Cache):
        cache.update_config(val=self.knative_exec, keys=["knative", "knativeExec"])
        self.resources.update_cache(cache)
        cache.update_config(
            val=self.credentials.serialize(), keys=["knative", "credentials"]
        )
