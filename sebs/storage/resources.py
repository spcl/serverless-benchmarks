from typing import cast, Optional, Tuple

from sebs.cache import Cache
from sebs.faas.config import Config, Resources
from sebs.faas.resources import SystemResources
from sebs.faas.storage import PersistentStorage
from sebs.faas.nosql import NoSQLStorage
from sebs.storage.minio import Minio
from sebs.storage.scylladb import ScyllaDB
from sebs.storage.config import (
    NoSQLStorageConfig,
    PersistentStorageConfig,
    ScyllaDBConfig,
    MinioConfig,
)
from sebs.utils import LoggingHandlers

import docker


class SelfHostedResources(Resources):
    def __init__(
        self,
        name: str,
        storage_cfg: Optional[PersistentStorageConfig] = None,
        nosql_storage_cfg: Optional[NoSQLStorageConfig] = None,
    ):
        super().__init__(name=name)
        self._object_storage = storage_cfg
        self._nosql_storage = nosql_storage_cfg

    @property
    def storage_config(self) -> Optional[PersistentStorageConfig]:
        return self._object_storage

    @property
    def nosql_storage_config(self) -> Optional[NoSQLStorageConfig]:
        return self._nosql_storage

    def serialize(self) -> dict:
        out: dict = {}

        if self._object_storage is not None:
            out = {**out, "storage": self._object_storage.serialize()}

        if self._nosql_storage is not None:
            out = {**out, "nosql": self._nosql_storage.serialize()}

        return out

    def update_cache(self, cache: Cache):
        super().update_cache(cache)
        if self._object_storage is not None:
            cast(MinioConfig, self._object_storage).update_cache(
                ["local", "resources", "storage"], cache
            )
        if self._nosql_storage is not None:
            cast(ScyllaDBConfig, self._nosql_storage).update_cache(
                ["local", "resources", "nosql"], cache
            )

    def _deserialize_storage(
        self, config: dict, cached_config: Optional[dict], storage_type: str
    ) -> Tuple[str, dict]:
        storage_impl = ""
        storage_config = {}

        # Check for new config
        if "storage" in config and storage_type in config["storage"]:
            storage_impl = config["storage"][storage_type]["type"]
            storage_config = config["storage"][storage_type][storage_impl]
            self.logging.info(
                "Using user-provided configuration of storage "
                f"type: {storage_type} for local containers."
            )

        # Load cached values
        elif (
            cached_config is not None
            and "resources" in cached_config
            and "storage" in cached_config["resources"]
            and "object" in cached_config["resources"]["storage"]
        ):
            storage_impl = cached_config["storage"]["object"]["type"]
            storage_config = cached_config["storage"]["object"][storage_impl]
            self.logging.info(
                f"Using cached configuration of storage type: {storage_type} for local container."
            )

        return storage_impl, storage_config

    @staticmethod
    def _deserialize(ret: "SelfHostedResources", config: dict, cached_config: dict):
        obj_storage_impl, obj_storage_cfg = ret._deserialize_storage(
            config, cached_config, "object"
        )

        if obj_storage_impl == "minio":
            ret._object_storage = MinioConfig.deserialize(obj_storage_cfg)
            ret.logging.info("Deserializing access data to Minio storage")
        elif obj_storage_impl != "":
            ret.logging.warning(f"Unknown object storage type: {obj_storage_impl}")
        else:
            ret.logging.info("No object storage available")

        nosql_storage_impl, nosql_storage_cfg = ret._deserialize_storage(
            config, cached_config, "nosql"
        )

        if nosql_storage_impl == "scylladb":
            ret._nosql_storage = ScyllaDBConfig.deserialize(nosql_storage_cfg)
            ret.logging.info("Deserializing access data to ScylladB NoSQL storage")
        elif nosql_storage_impl != "":
            ret.logging.warning(f"Unknown NoSQL storage type: {nosql_storage_impl}")
        else:
            ret.logging.info("No NoSQL storage available")


class SelfHostedSystemResources(SystemResources):
    def __init__(
        self,
        config: Config,
        cache_client: Cache,
        docker_client: docker.client,
        logger_handlers: LoggingHandlers,
    ):
        super().__init__(config, cache_client, docker_client)

        self._logging_handlers = logger_handlers
        self._storage: Optional[PersistentStorage] = None
        self._nosql_storage: Optional[NoSQLStorage] = None

    """
        Create wrapper object for minio storage and fill buckets.
        Starts minio as a Docker instance, using always fresh buckets.

        :param benchmark:
        :param buckets: number of input and output buckets
        :param replace_existing: not used.
        :return: Azure storage instance
    """

    def get_storage(self, replace_existing: Optional[bool] = None) -> PersistentStorage:
        if self._storage is None:
            storage_config = cast(SelfHostedResources, self._config.resources).storage_config
            if storage_config is None:
                self.logging.error(
                    "The local deployment is missing the configuration of pre-allocated storage!"
                )
                raise RuntimeError("Cannot run local deployment without any object storage")

            if isinstance(storage_config, MinioConfig):
                self._storage = Minio.deserialize(
                    storage_config,
                    self._cache_client,
                    self._config.resources,
                )
                self._storage.logging_handlers = self._logging_handlers
            else:
                self.logging.error(
                    "The local deployment does not support "
                    f"the object storage config type: {type(storage_config)}!"
                )
                raise RuntimeError("Cannot work with the provided object storage!")

        elif replace_existing is not None:
            self._storage.replace_existing = replace_existing
        return self._storage

    def get_nosql_storage(self) -> NoSQLStorage:
        if self._nosql_storage is None:
            storage_config = cast(SelfHostedResources, self._config.resources).nosql_storage_config
            if storage_config is None:
                self.logging.error(
                    "The local deployment is missing the configuration "
                    "of pre-allocated NoSQL storage!"
                )
                raise RuntimeError("Cannot allocate NoSQL storage!")

            if isinstance(storage_config, ScyllaDBConfig):
                self._nosql_storage = ScyllaDB.deserialize(
                    storage_config, self._cache_client, self._config.resources
                )
                self._nosql_storage.logging_handlers = self._logging_handlers
            else:
                self.logging.error(
                    "The local deployment does not support "
                    f"the NoSQL storage config type: {type(storage_config)}!"
                )
                raise RuntimeError("Cannot work with the provided NoSQL storage!")

        return self._nosql_storage
