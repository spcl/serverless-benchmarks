"""Resource management for self-hosted storage deployments in SeBS.

This module provides resource management classes for self-hosted storage
deployments, including both object storage (MinIO) and NoSQL storage (ScyllaDB).
It handles configuration deserialization, container lifecycle management, and
provides unified interfaces for accessing storage services.

Key Classes:
    SelfHostedResources: Configuration management for self-hosted storage resources
    SelfHostedSystemResources: System-level resource management and service provisioning

The module supports:
    - MinIO for S3-compatible object storage
    - ScyllaDB for DynamoDB-compatible NoSQL storage
    - Configuration caching and deserialization
    - Docker container lifecycle management
    - Dynamic service discovery and connection configuration
"""

import docker
from typing import cast, Dict, Optional, Tuple, Any

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


class SelfHostedResources(Resources):
    """Resource configuration for self-hosted storage deployments.

    This class manages configuration for self-hosted storage services,
    including object storage (MinIO) and NoSQL storage (ScyllaDB). It provides
    serialization, caching, and deserialization capabilities for storage
    configurations.

    Attributes:
        _object_storage: Configuration for object storage (MinIO)
        _nosql_storage: Configuration for NoSQL storage (ScyllaDB)
    """

    def __init__(
        self,
        name: str,
        storage_cfg: Optional[PersistentStorageConfig] = None,
        nosql_storage_cfg: Optional[NoSQLStorageConfig] = None,
    ):
        """Initialize self-hosted resources configuration.

        Args:
            name: Name of the deployment/resource group
            storage_cfg: Configuration for object storage service
            nosql_storage_cfg: Configuration for NoSQL storage service
        """
        super().__init__(name=name)
        self._object_storage = storage_cfg
        self._nosql_storage = nosql_storage_cfg

    @property
    def storage_config(self) -> Optional[PersistentStorageConfig]:
        """Get the object storage configuration.

        Returns:
            Optional[PersistentStorageConfig]: Object storage configuration or None
        """
        return self._object_storage

    @property
    def nosql_storage_config(self) -> Optional[NoSQLStorageConfig]:
        """Get the NoSQL storage configuration.

        Returns:
            Optional[NoSQLStorageConfig]: NoSQL storage configuration or None
        """
        return self._nosql_storage

    def serialize(self) -> Dict[str, Any]:
        """Serialize the resource configuration to a dictionary.

        Returns:
            Dict[str, Any]: Serialized configuration containing storage and/or nosql sections
        """
        out: Dict[str, Any] = {}

        if self._object_storage is not None:
            out = {**out, "storage": self._object_storage.serialize()}

        if self._nosql_storage is not None:
            out = {**out, "nosql": self._nosql_storage.serialize()}

        return out

    def update_cache(self, cache: Cache) -> None:
        """Update the configuration cache with current resource settings.

        Stores both object storage and NoSQL storage configurations in the
        cache for later retrieval.

        Args:
            cache: Cache instance to store configurations in
        """
        super().update_cache(cache)
        if self._object_storage is not None:
            cast(MinioConfig, self._object_storage).update_cache(
                [self._name, "resources", "storage"], cache
            )
        if self._nosql_storage is not None:
            cast(ScyllaDBConfig, self._nosql_storage).update_cache(
                [self._name, "resources", "nosql"], cache
            )

    def _deserialize_storage(
        self, config: Dict[str, Any], cached_config: Optional[Dict[str, Any]], storage_type: str
    ) -> Tuple[str, Dict[str, Any]]:
        """Deserialize storage configuration from config or cache.

        Attempts to load storage configuration from the provided config first,
        then falls back to cached configuration if available.

        Args:
            config: Current configuration dictionary
            cached_config: Previously cached configuration dictionary
            storage_type: Type of storage to deserialize ('object' or 'nosql')

        Returns:
            Tuple[str, Dict[str, Any]]: Storage implementation name and configuration
        """
        storage_impl = ""
        storage_config: Dict[str, Any] = {}

        # Check for new config
        if "storage" in config and storage_type in config["storage"]:
            storage_impl = config["storage"][storage_type]["type"]
            storage_config = config["storage"][storage_type][storage_impl]
            self.logging.info(
                "Using user-provided configuration of storage "
                f"type: {storage_type} for {self._name} containers."
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
                f"Using cached configuration of storage type: "
                f"{storage_type} for {self._name} container."
            )

        return storage_impl, storage_config

    @staticmethod
    def _deserialize(
        ret: "SelfHostedResources", config: Dict[str, Any], cached_config: Optional[Dict[str, Any]]
    ) -> None:
        """Deserialize storage configurations from config and cache data.

        Populates the SelfHostedResources instance with storage configurations
        loaded from the provided configuration and cached data.

        Args:
            ret: SelfHostedResources instance to populate
            config: Current configuration dictionary
            cached_config: Previously cached configuration dictionary
        """
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
    """System-level resource management for self-hosted storage deployments.

    This class manages the lifecycle and provisioning of self-hosted storage
    services, including MinIO object storage and ScyllaDB NoSQL storage. It
    handles container management, service initialization, and provides unified
    access to storage services.

    Attributes:
        _name: Name of the deployment
        _logging_handlers: Logging configuration handlers
        _storage: Active persistent storage instance (MinIO)
        _nosql_storage: Active NoSQL storage instance (ScyllaDB)
    """

    def __init__(
        self,
        name: str,
        config: Config,
        cache_client: Cache,
        docker_client: docker.client,
        logger_handlers: LoggingHandlers,
    ):
        """Initialize system resources for self-hosted storage.

        Args:
            name: Name of the deployment
            config: SeBS configuration object
            cache_client: Cache client for configuration persistence
            docker_client: Docker client for container management
            logger_handlers: Logging configuration handlers
        """
        super().__init__(config, cache_client, docker_client)

        self._name = name
        self._logging_handlers = logger_handlers
        self._storage: Optional[PersistentStorage] = None
        self._nosql_storage: Optional[NoSQLStorage] = None

    def get_storage(self, replace_existing: Optional[bool] = None) -> PersistentStorage:
        """Get or create a persistent storage instance.

        Creates a MinIO storage instance if one doesn't exist, or returns the
        existing instance. The storage is configured using the deployment's
        storage configuration.

        Args:
            replace_existing: Whether to replace existing buckets (optional)

        Returns:
            PersistentStorage: MinIO storage instance

        Raises:
            RuntimeError: If storage configuration is missing or unsupported
        """
        if self._storage is None:
            storage_config = cast(SelfHostedResources, self._config.resources).storage_config
            if storage_config is None:
                self.logging.error(
                    f"The {self._name} deployment is missing the "
                    "configuration of pre-allocated storage!"
                )
                raise RuntimeError(f"Cannot run {self._name} deployment without any object storage")

            if isinstance(storage_config, MinioConfig):
                self._storage = Minio.deserialize(
                    storage_config,
                    self._cache_client,
                    self._config.resources,
                )
                self._storage.logging_handlers = self._logging_handlers
            else:
                self.logging.error(
                    f"The {self._name} deployment does not support "
                    f"the object storage config type: {type(storage_config)}!"
                )
                raise RuntimeError("Cannot work with the provided object storage!")

        elif replace_existing is not None:
            self._storage.replace_existing = replace_existing
        return self._storage

    def get_nosql_storage(self) -> NoSQLStorage:
        """Get or create a NoSQL storage instance.

        Creates a ScyllaDB storage instance if one doesn't exist, or returns the
        existing instance. The storage is configured using the deployment's
        NoSQL storage configuration.

        Returns:
            NoSQLStorage: ScyllaDB storage instance

        Raises:
            RuntimeError: If NoSQL storage configuration is missing or unsupported
        """
        if self._nosql_storage is None:
            storage_config = cast(SelfHostedResources, self._config.resources).nosql_storage_config
            if storage_config is None:
                self.logging.error(
                    f"The {self._name} deployment is missing the configuration "
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
                    f"The {self._name} deployment does not support "
                    f"the NoSQL storage config type: {type(storage_config)}!"
                )
                raise RuntimeError("Cannot work with the provided NoSQL storage!")

        return self._nosql_storage
