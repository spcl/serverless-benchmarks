from sebs.cache import Cache
from sebs.faas.config import Resources, Config
from sebs.utils import LoggingHandlers
from sebs.storage.config import MinioConfig

from typing import cast, Optional


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

        # Check for new config - overrides but check if it's different
        if "docker_registry" in config:

            KnativeResources.initialize(ret, config["docker_registry"])
            ret.logging.info("Using user-provided Docker registry for Knative.")
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
            KnativeResources.initialize(ret, cached_config["resources"]["docker"])
            ret.logging_handlers = handlers
            ret.logging.info("Using cached Docker registry for Knative")
        else:
            ret = KnativeResources()
            ret.logging.info("Using default Docker registry for Knative.")
            ret.logging_handlers = handlers
            ret._registry_updated = True

        # Check for new config
        if "storage" in config:
            ret._storage = MinioConfig.deserialize(config["storage"])
            ret.logging.info(
                "Using user-provided configuration of storage for Knative."
            )

            # check if there has been an update
            if not (
                cached_config
                and "resources" in cached_config
                and "storage" in cached_config["resources"]
                and cached_config["resources"]["storage"] == config["storage"]
            ):
                ret.logging.info(
                    "User-provided configuration is different from cached storage, "
                    "we will update existing Knative actions."
                )
                ret._storage_updated = True

        # Load cached values
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
        self.knative_exec = config["knativeExec"]
        self.cache = cache

    @property
    def resources(self) -> KnativeResources:
        return self._resources

    @staticmethod
    def initialize(cfg: Config, dct: dict):
        cfg._region = dct["region"]

    def serialize(self) -> dict:
        return {
            "name": self._name,
            "region": self._region,
            "knativeExec": self.knative_exec,
            "resources": self._resources.serialize(),
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
        return res

    def update_cache(self, cache: Cache):
        cache.update_config(val=self.knative_exec, keys=["knative", "knativeExec"])
        self.resources.update_cache(cache)
