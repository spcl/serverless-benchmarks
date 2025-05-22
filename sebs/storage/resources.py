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
    """
    Manages resources for self-hosted FaaS deployments, such as local Minio
    for object storage and ScyllaDB for NoSQL storage.
    """
    def __init__(
        self,
        name: str,
        storage_cfg: Optional[PersistentStorageConfig] = None,
        nosql_storage_cfg: Optional[NoSQLStorageConfig] = None,
    ):
        """
        Initialize SelfHostedResources.

        :param name: Name of the self-hosted platform (e.g., "local", "openwhisk").
        :param storage_cfg: Optional configuration for persistent object storage (e.g., MinioConfig).
        :param nosql_storage_cfg: Optional configuration for NoSQL storage (e.g., ScyllaDBConfig).
        """
        super().__init__(name=name)
        self._object_storage: Optional[PersistentStorageConfig] = storage_cfg
        self._nosql_storage: Optional[NoSQLStorageConfig] = nosql_storage_cfg

    @property
    def storage_config(self) -> Optional[PersistentStorageConfig]:
        """Configuration for the self-hosted object storage (e.g., Minio)."""
        return self._object_storage

    @property
    def nosql_storage_config(self) -> Optional[NoSQLStorageConfig]:
        """Configuration for the self-hosted NoSQL storage (e.g., ScyllaDB)."""
        return self._nosql_storage

    def serialize(self) -> dict:
        """
        Serialize the self-hosted resource configurations to a dictionary.

        Includes configurations for object storage and NoSQL storage if they are set.

        :return: Dictionary representation of the self-hosted resources.
        """
        out: dict = {}
        # Call super().serialize() to include base Resource fields like buckets, resource_id
        out = {**super().serialize(), **out}


        if self._object_storage is not None:
            out["object_storage"] = self._object_storage.serialize() # Changed key from "storage"

        if self._nosql_storage is not None:
            out["nosql_storage"] = self._nosql_storage.serialize() # Changed key from "nosql"

        return out

    def update_cache(self, cache: Cache):
        """
        Update the SeBS cache with the configurations of self-hosted resources.

        Saves object storage (Minio) and NoSQL storage (ScyllaDB) configurations.

        :param cache: The Cache client instance.
        """
        super().update_cache(cache)
        if self._object_storage is not None and isinstance(self._object_storage, MinioConfig):
            self._object_storage.update_cache( # MinioConfig has its own update_cache
                [self._name, "resources", "object_storage", "minio"], cache # More specific path
            )
        if self._nosql_storage is not None and isinstance(self._nosql_storage, ScyllaDBConfig):
            self._nosql_storage.update_cache( # ScyllaDBConfig has its own update_cache
                [self._name, "resources", "nosql_storage", "scylladb"], cache # More specific path
            )

    def _deserialize_storage_config( # Renamed for clarity, takes specific storage_type_key
        self,
        user_config: dict, # User-provided config for the entire 'resources' section
        cached_resource_config: Optional[dict], # Cached 'resources' section
        storage_type_key: str, # "object_storage" or "nosql_storage"
        default_type_map: Dict[str, Type[PersistentStorageConfig] | Type[NoSQLStorageConfig]]
    ) -> Optional[PersistentStorageConfig | NoSQLStorageConfig]:
        """
        Helper to deserialize a specific type of storage configuration (object or NoSQL).

        It checks user config first, then cached config.

        :param user_config: The 'resources' part of the user-provided configuration.
        :param cached_resource_config: The 'resources' part of the cached configuration.
        :param storage_type_key: The key for this storage type (e.g., "object_storage").
        :param default_type_map: Maps type strings (e.g., "minio") to config classes.
        :return: Deserialized storage configuration object or None.
        """
        storage_details_user = user_config.get(storage_type_key)
        storage_details_cached = (cached_resource_config or {}).get(storage_type_key)

        final_storage_details = None
        source_msg = ""

        if storage_details_user:
            final_storage_details = storage_details_user
            source_msg = "user-provided"
        elif storage_details_cached:
            final_storage_details = storage_details_cached
            source_msg = "cached"

        if final_storage_details:
            storage_impl_type_str = final_storage_details.get("type")
            if storage_impl_type_str and storage_impl_type_str in default_type_map:
                config_class = default_type_map[storage_impl_type_str]
                # Pass the actual config dict for that type (e.g., content of "minio" key)
                # The structure is assumed: storage_type_key: {"type": "minio", "minio": {...actual_config...}}
                # Or, if simpler: storage_type_key: {"type": "minio", ...actual_config_kv_pairs...}
                # Assuming the latter simpler structure for now based on MinioConfig.deserialize
                self.logging.info(
                    f"Using {source_msg} configuration for {storage_type_key} (type: {storage_impl_type_str})."
                )
                return config_class.deserialize(final_storage_details)
            elif storage_impl_type_str:
                self.logging.warning(f"Unknown {storage_type_key} type: {storage_impl_type_str}")
            else:
                 self.logging.info(f"No 'type' specified for {storage_type_key} in {source_msg} config.")
        else:
            self.logging.info(f"No {storage_type_key} configuration provided or found in cache.")
        return None


    @staticmethod
    def _deserialize(
        ret: "SelfHostedResources",
        user_resources_config: dict, # The 'resources' part of user config
        cached_resources_config: Optional[dict] # The 'resources' part of cached config
    ):
        """
        Deserialize self-hosted storage configurations (object and NoSQL).

        Populates `_object_storage` and `_nosql_storage` attributes of the `ret` instance.

        :param ret: The SelfHostedResources instance to populate.
        :param user_resources_config: The 'resources' section from user-provided configuration.
        :param cached_resources_config: The 'resources' section from cached configuration, if any.
        """
        # Define type maps for deserialization
        object_storage_type_map = {"minio": MinioConfig}
        nosql_storage_type_map = {"scylladb": ScyllaDBConfig}

        ret._object_storage = ret._deserialize_storage_config(
            user_resources_config, cached_resources_config, "object_storage", object_storage_type_map
        )
        ret._nosql_storage = ret._deserialize_storage_config(
            user_resources_config, cached_resources_config, "nosql_storage", nosql_storage_type_map
        )


class SelfHostedSystemResources(SystemResources):
    """
    Manages system resources for self-hosted FaaS deployments.

    This class provides access to self-hosted persistent storage (Minio) and
    NoSQL storage (ScyllaDB) based on the provided configuration.
    """
    def __init__(
        self,
        name: str, # Name of the self-hosted platform, e.g., "local", "openwhisk"
        config: Config, # The top-level platform Config (e.g., LocalConfig, OpenWhiskConfig)
        cache_client: Cache,
        docker_client: docker.client,
        logger_handlers: LoggingHandlers,
    ):
        """
        Initialize SelfHostedSystemResources.

        :param name: Name of the self-hosted platform.
        :param config: The top-level configuration for the platform.
        :param cache_client: Cache client instance.
        :param docker_client: Docker client instance.
        :param logger_handlers: Logging handlers.
        """
        super().__init__(config, cache_client, docker_client)
        self._name = name # Platform name, e.g. "local" or "openwhisk"
        self._logging_handlers = logger_handlers
        self._storage: Optional[PersistentStorage] = None
        self._nosql_storage: Optional[NoSQLStorage] = None

    def get_storage(self, replace_existing: Optional[bool] = None) -> PersistentStorage:
        """
        Get or initialize the self-hosted persistent storage client (Minio).

        If the client hasn't been initialized, it deserializes the MinioConfig
        from the system configuration and creates a Minio client instance.

        :param replace_existing: If True, replace existing files in input buckets.
                                 Defaults to False if None.
        :return: Minio persistent storage client.
        :raises RuntimeError: If Minio configuration is missing or invalid.
        """
        if self._storage is None:
            # self._config.resources should be SelfHostedResources instance
            sh_resources = cast(SelfHostedResources, self._config.resources)
            storage_config = sh_resources.storage_config
            if storage_config is None:
                self.logging.error(
                    f"The {self._name} deployment is missing the "
                    "configuration of self-hosted object storage (e.g., Minio)!"
                )
                raise RuntimeError(f"Cannot run {self._name} deployment without object storage config.")

            if isinstance(storage_config, MinioConfig):
                # Minio.deserialize expects the MinioConfig itself, cache, and parent Resources
                self._storage = Minio.deserialize(
                    storage_config,
                    self._cache_client,
                    self._config.resources, # Pass the parent Resources object
                )
                self._storage.logging_handlers = self._logging_handlers
                if replace_existing is not None: # Apply replace_existing if provided now
                    self._storage.replace_existing = replace_existing
            else:
                self.logging.error(
                    f"The {self._name} deployment does not support "
                    f"the object storage config type: {type(storage_config)}!"
                )
                raise RuntimeError("Cannot work with the provided object storage config type!")

        elif replace_existing is not None: # If storage already exists, just update replace_existing
            self._storage.replace_existing = replace_existing
        return self._storage

    def get_nosql_storage(self) -> NoSQLStorage:
        """
        Get or initialize the self-hosted NoSQL storage client (ScyllaDB).

        If the client hasn't been initialized, it deserializes the ScyllaDBConfig
        from the system configuration and creates a ScyllaDB client instance.

        :return: ScyllaDB NoSQL storage client.
        :raises RuntimeError: If ScyllaDB configuration is missing or invalid.
        """
        if self._nosql_storage is None:
            sh_resources = cast(SelfHostedResources, self._config.resources)
            nosql_config = sh_resources.nosql_storage_config
            if nosql_config is None:
                self.logging.error(
                    f"The {self._name} deployment is missing the configuration "
                    "of self-hosted NoSQL storage (e.g., ScyllaDB)!"
                )
                raise RuntimeError(f"Cannot run {self._name} deployment without NoSQL storage config.")

            if isinstance(nosql_config, ScyllaDBConfig):
                 # ScyllaDB.deserialize expects ScyllaDBConfig, cache, and parent Resources
                self._nosql_storage = ScyllaDB.deserialize(
                    nosql_config, self._cache_client, self._config.resources
                )
                self._nosql_storage.logging_handlers = self._logging_handlers
            else:
                self.logging.error(
                    f"The {self._name} deployment does not support "
                    f"the NoSQL storage config type: {type(nosql_config)}!"
                )
                raise RuntimeError("Cannot work with the provided NoSQL storage config type!")
        return self._nosql_storage
