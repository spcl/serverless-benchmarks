from typing import cast, Optional, Set

from sebs.cache import Cache
from sebs.faas.config import Config, Credentials, Resources
from sebs.storage.resources import SelfHostedResources
from sebs.storage.config import NoSQLStorageConfig, PersistentStorageConfig
from sebs.utils import LoggingHandlers


class LocalCredentials(Credentials):
    """Credentials for local FaaS deployment (no specific credentials needed)."""
    def serialize(self) -> dict:
        """
        Serialize LocalCredentials to a dictionary. Returns an empty dictionary
        as no specific credentials are stored for local deployments.

        :return: Empty dictionary.
        """
        return {}

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Credentials:
        """
        Deserialize LocalCredentials. Returns a new LocalCredentials instance
        as no specific configuration is needed from the input dictionary or cache.

        :param config: Configuration dictionary (not used).
        :param cache: Cache object (not used).
        :param handlers: Logging handlers (not used for actual credential loading here).
        :return: A LocalCredentials instance.
        """
        return LocalCredentials()


class LocalResources(SelfHostedResources):
    """
    Manages resources for local FaaS deployments.

    This includes tracking allocated ports for locally running services.
    Local deployments do not typically require extensive cloud resource management,
    so caching and storing resource details are minimal.
    """
    def __init__(
        self,
        storage_cfg: Optional[PersistentStorageConfig] = None,
        nosql_storage_cfg: Optional[NoSQLStorageConfig] = None,
    ):
        """
        Initialize LocalResources.

        :param storage_cfg: Configuration for persistent storage (e.g., local Minio).
        :param nosql_storage_cfg: Configuration for NoSQL storage (e.g., local ScyllaDB).
        """
        self._path: str = "" # Path for local storage, if applicable (seems unused currently)
        super().__init__("local", storage_cfg, nosql_storage_cfg)
        self._allocated_ports: Set[int] = set()

    @property
    def allocated_ports(self) -> Set[int]: # Explicitly Set[int]
        """Set of network ports allocated for local services."""
        return self._allocated_ports

    def serialize(self) -> dict:
        """
        Serialize LocalResources to a dictionary for caching.

        Includes allocated ports along with any information from the parent class.

        :return: Dictionary representation of LocalResources.
        """
        out = super().serialize()
        out["allocated_ports"] = list(self._allocated_ports) # Convert set to list for JSON
        return out

    @staticmethod
    def initialize(res: Resources, config: dict):
        """
        Initialize LocalResources attributes from a dictionary.

        Populates allocated ports if present in the configuration.

        :param res: Resources object to initialize (cast to LocalResources).
        :param config: Dictionary containing resource configurations.
        """
        resources = cast(LocalResources, res)
        # Call parent initializer if it exists and handles common fields like resources_id
        super(LocalResources, LocalResources).initialize(resources, config) # Ensure base class init is called

        if "allocated_ports" in config:
            resources._allocated_ports = set(config["allocated_ports"])

    def update_cache(self, cache: Cache):
        """
        Update the cache with LocalResource details, specifically allocated ports.

        :param cache: Cache object.
        """
        super().update_cache(cache)
        cache.update_config(
            val=list(self._allocated_ports), keys=["local", "resources", "allocated_ports"]
        )

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Resources:
        """
        Deserialize LocalResources from configuration or cache.

        Prioritizes cached configuration for allocated ports if available.

        :param config: Configuration dictionary.
        :param cache: Cache object.
        :param handlers: Logging handlers.
        :return: LocalResources instance.
        """
        ret = LocalResources()
        # _deserialize from SelfHostedResources likely handles storage_cfg and nosql_storage_cfg
        # It needs to be called appropriately. Assuming it's part of the logic.
        # The original call `ret._deserialize(ret, config, cached_config)` implies
        # `_deserialize` is a method of LocalResources or its parent that takes these args.
        # Let's assume SelfHostedResources has a suitable _deserialize or similar mechanism.
        
        # For SelfHostedResources part (storage_cfg, nosql_storage_cfg)
        # This part might need adjustment based on how SelfHostedResources._deserialize is structured
        # If SelfHostedResources.deserialize exists and is static:
        #   temp_self_hosted = SelfHostedResources.deserialize(config, cache, handlers)
        #   ret._storage = temp_self_hosted._storage # or however these are stored
        #   ret._nosql_storage = temp_self_hosted._nosql_storage
        # Or, if _deserialize is an instance method of SelfHostedResources:
        ret._deserialize(ret, config, cache.get_config("local")) # Pass local part of cache

        cached_local_resources_config = cache.get_config("local", {}).get("resources", {})

        # Initialize using the more specific (potentially cached) config first for local parts
        if cached_local_resources_config:
            LocalResources.initialize(ret, cached_local_resources_config)
            ret.logging_handlers = handlers # Set handlers after initialization
            ret.logging.info("Using cached resources for Local (ports, etc.)")
        elif "resources" in config: # Fallback to main config if no specific cache for resources
            LocalResources.initialize(ret, config["resources"])
            ret.logging_handlers = handlers
            ret.logging.info("No cached local resources found, using user configuration for Local.")
        else: # Initialize with empty if no config found at all
            LocalResources.initialize(ret, {})
            ret.logging_handlers = handlers
            ret.logging.info("No local resources configuration found, initializing empty for Local.")
            
        return ret


class LocalConfig(Config):
    """Configuration for local FaaS deployments."""
    def __init__(self):
        """Initialize a new LocalConfig with default LocalCredentials and LocalResources."""
        super().__init__(name="local")
        self._credentials = LocalCredentials()
        self._resources = LocalResources()

    @staticmethod
    def typename() -> str:
        """Return the type name of the LocalConfig class."""
        return "Local.Config"

    @staticmethod
    def initialize(cfg: Config, dct: dict):
        """
        Initialize LocalConfig attributes. Currently does nothing as local
        deployments have minimal region-like configuration at this level.

        :param cfg: Config object to initialize.
        :param dct: Dictionary containing configuration values.
        """
        # Local deployments don't typically have a "region" in the cloud sense.
        # The base Config class handles _region, but it might remain empty or unused for local.
        super(LocalConfig, LocalConfig).initialize(cfg, dct if 'region' in dct else {'region': ''})


    @property
    def credentials(self) -> LocalCredentials:
        """Return the LocalCredentials instance."""
        return self._credentials

    @property
    def resources(self) -> LocalResources:
        """Return the LocalResources instance."""
        return self._resources

    @resources.setter
    def resources(self, val: LocalResources):
        """Set the LocalResources instance."""
        self._resources = val

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Config:
        """
        Deserialize a LocalConfig object.

        Deserializes LocalResources and associates them with a new LocalConfig instance.

        :param config: Configuration dictionary (can be specific to 'local' or general).
        :param cache: Cache object.
        :param handlers: Logging handlers.
        :return: A LocalConfig instance.
        """
        config_obj = LocalConfig()
        # Pass the relevant part of the config to LocalResources.deserialize
        # If 'config' is already the 'local' part, pass it directly.
        # Otherwise, if 'config' is the top-level config, extract 'local.resources' if present.
        resources_config = config.get("resources", config) # Fallback to passing full config if 'resources' not a key
        config_obj.resources = cast(
            LocalResources, LocalResources.deserialize(resources_config, cache, handlers)
        )
        config_obj.logging_handlers = handlers
        # Initialize LocalConfig specific parts if any (e.g. region, though less relevant for local)
        LocalConfig.initialize(config_obj, config)
        return config_obj

    def serialize(self) -> dict:
        """
        Serialize LocalConfig to a dictionary.

        Includes 'name', 'region' (if set), and serialized resources.

        :return: Dictionary representation of LocalConfig.
        """
        out = {
            "name": "local",
            "region": self._region, # Region might be empty/irrelevant for local
            "resources": self._resources.serialize()
        }
        return out

    def update_cache(self, cache: Cache):
        """
        Update the cache with LocalConfig details.

        Primarily updates resource configurations in the cache.

        :param cache: Cache object.
        """
        # LocalConfig itself doesn't have much to cache besides what resources handle.
        # If region or other specific LocalConfig fields were important, they'd be cached here.
        self.resources.update_cache(cache)
