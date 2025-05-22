from __future__ import annotations

from sebs.cache import Cache
from sebs.faas.config import Credentials, Resources, Config
from sebs.utils import LoggingHandlers
from sebs.storage.resources import SelfHostedResources

from typing import cast, Optional


class OpenWhiskCredentials(Credentials):
    """Credentials for OpenWhisk (no specific credentials typically needed by SeBS)."""
    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Credentials:
        """
        Deserialize OpenWhiskCredentials. Returns a new OpenWhiskCredentials instance
        as no specific configuration is needed from the input dictionary or cache for SeBS's use.
        OpenWhisk authentication is usually handled via `wsk` CLI properties file.

        :param config: Configuration dictionary (not used).
        :param cache: Cache object (not used).
        :param handlers: Logging handlers (not used for actual credential loading here).
        :return: An OpenWhiskCredentials instance.
        """
        return OpenWhiskCredentials()

    def serialize(self) -> dict:
        """
        Serialize OpenWhiskCredentials to a dictionary. Returns an empty dictionary.

        :return: Empty dictionary.
        """
        return {}


class OpenWhiskResources(SelfHostedResources):
    """
    Manages resources for OpenWhisk deployments, including Docker registry details.
    Inherits from SelfHostedResources for common self-hosted storage/NoSQL configurations.
    """
    def __init__(
        self,
        registry: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        registry_updated: bool = False, # Indicates if registry details were newly provided vs cached
    ):
        """
        Initialize OpenWhiskResources.

        :param registry: Docker registry URL for OpenWhisk actions.
        :param username: Username for the Docker registry.
        :param password: Password for the Docker registry.
        :param registry_updated: Flag indicating if registry details are new or updated.
        """
        super().__init__(name="openwhisk")
        self._docker_registry = registry if registry != "" else None
        self._docker_username = username if username != "" else None
        self._docker_password = password if password != "" else None
        self._registry_updated = registry_updated
        self._storage_updated = False # Related to SelfHostedResources, indicates if storage config changed

    @staticmethod
    def typename() -> str:
        """Return the type name of the OpenWhiskResources class."""
        return "OpenWhisk.Resources"

    @property
    def docker_registry(self) -> Optional[str]:
        """Docker registry URL for OpenWhisk function images."""
        return self._docker_registry

    @property
    def docker_username(self) -> Optional[str]:
        """Username for the Docker registry."""
        return self._docker_username

    @property
    def docker_password(self) -> Optional[str]:
        """Password for the Docker registry."""
        return self._docker_password

    @property
    def storage_updated(self) -> bool:
        """Flag indicating if self-hosted storage configuration was updated."""
        return self._storage_updated

    @property
    def registry_updated(self) -> bool:
        """Flag indicating if Docker registry details were updated."""
        return self._registry_updated

    @staticmethod
    def initialize(res: Resources, dct: dict):
        """
        Initialize OpenWhiskResources-specific attributes from a dictionary.
        This focuses on Docker registry details. Base class handles other parts.

        :param res: Resources object to initialize (cast to OpenWhiskResources).
        :param dct: Dictionary containing 'registry', 'username', and 'password' for Docker.
        """
        ret = cast(OpenWhiskResources, res)
        # Assuming dct here is specifically the 'docker_registry' part of the config
        ret._docker_registry = dct.get("registry")
        ret._docker_username = dct.get("username")
        ret._docker_password = dct.get("password")
        # Note: SelfHostedResources.initialize should be called by the caller if needed
        # or integrated into a common initialization flow.

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Resources:
        """
        Deserialize OpenWhiskResources from configuration or cache.

        Handles Docker registry details and calls parent for self-hosted storage/NoSQL.

        :param config: Configuration dictionary, may contain 'docker_registry'.
        :param cache: Cache object for retrieving cached resource details.
        :param handlers: Logging handlers.
        :return: OpenWhiskResources instance.
        """
        cached_config = cache.get_config("openwhisk")
        ret = OpenWhiskResources()
        
        # Initialize SelfHostedResources parts first (storage, nosql)
        # The `_deserialize` method is from SelfHostedResources and handles its specific fields.
        # It needs the relevant part of the config and cache.
        # Assuming `config` might be the top-level user config, and `cached_config` is the 'openwhisk' section.
        ret._deserialize(ret, config.get("resources", {}), cached_config.get("resources") if cached_config else None)


        # Docker registry details handling
        user_docker_config = config.get("docker_registry")
        cached_docker_config = (cached_config or {}).get("resources", {}).get("docker")

        if user_docker_config:
            OpenWhiskResources.initialize(ret, user_docker_config)
            ret.logging.info("Using user-provided Docker registry for OpenWhisk.")
            if not cached_docker_config or cached_docker_config != user_docker_config:
                ret._registry_updated = True
        elif cached_docker_config:
            OpenWhiskResources.initialize(ret, cached_docker_config)
            ret.logging.info("Using cached Docker registry for OpenWhisk.")
        else:
            # Defaults to None if no config provided and nothing in cache
            ret.logging.info("Using default (None) Docker registry for OpenWhisk.")
            ret._registry_updated = True # Considered "updated" as it's the first time or different from non-existence

        ret.logging_handlers = handlers
        return ret

    def update_cache(self, cache: Cache):
        """
        Update the cache with OpenWhisk resource details, including Docker registry.

        :param cache: Cache object.
        """
        super().update_cache(cache) # Handles SelfHostedResources parts
        docker_details = {
            "registry": self.docker_registry,
            "username": self.docker_username,
            "password": self.docker_password, # Note: Storing passwords in cache might be a security concern.
        }
        cache.update_config_section(keys=["openwhisk", "resources", "docker"], section_dict=docker_details)


    def serialize(self) -> dict:
        """
        Serialize OpenWhiskResources to a dictionary.

        Includes Docker registry details and calls parent for self-hosted parts.

        :return: Dictionary representation of OpenWhiskResources.
        """
        out: dict = {
            **super().serialize(), # Serializes SelfHostedResources parts
            "docker": { # Nest docker details for better organization in cache
                 "registry": self.docker_registry,
                 "username": self.docker_username,
                 "password": self.docker_password, # Again, password in cache.
            }
        }
        return out


class OpenWhiskConfig(Config):
    """
    Configuration for OpenWhisk deployments.

    Includes settings for `wsk` CLI, experimental features, and management
    of cluster and storage lifecycle.
    """
    # Type hints for attributes specific to OpenWhiskConfig
    shutdownStorage: bool
    removeCluster: bool
    wsk_exec: str
    wsk_bypass_security: bool
    experimentalManifest: bool
    # cache is passed to __init__ but not stored as self.cache directly, used for cached_config in deserialize
    # It's unusual for a config object to hold the cache client itself.

    def __init__(self, config_values: dict, cached_config_for_resources: Optional[dict] = None):
        """
        Initialize OpenWhiskConfig.

        :param config_values: Dictionary of OpenWhisk specific configuration values.
        :param cached_config_for_resources: Optional cached configuration for resources,
                                            used if OpenWhiskResources needs it during init.
                                            (Note: The original `cache` arg was unused in this method)
        """
        super().__init__(name="openwhisk")
        self._credentials = OpenWhiskCredentials() # OpenWhisk typically doesn't use SeBS-managed creds
        # Resources are initialized here, potentially using parts of config_values or cached_config_for_resources
        # This part is a bit complex due to how OpenWhiskResources.deserialize is structured.
        # For simplicity, let's assume OpenWhiskResources can be default-initialized or needs specific dict.
        # The deserialize method is the primary way resources get populated.
        self._resources = OpenWhiskResources()

        self.shutdownStorage = config_values.get("shutdownStorage", False)
        self.removeCluster = config_values.get("removeCluster", False)
        self.wsk_exec = config_values.get("wskExec", "wsk") # Default to 'wsk'
        self.wsk_bypass_security = config_values.get("wskBypassSecurity", False)
        self.experimentalManifest = config_values.get("experimentalManifest", False)
        # self.cache = cache # Storing cache client in config is unusual.

    @property
    def credentials(self) -> OpenWhiskCredentials:
        """Return the OpenWhiskCredentials instance."""
        return self._credentials

    @property
    def resources(self) -> OpenWhiskResources:
        """Return the OpenWhiskResources instance."""
        return self._resources

    @staticmethod
    def initialize(cfg: Config, dct: dict):
        """
        Initialize OpenWhiskConfig attributes from a dictionary.
        This method populates fields like `wsk_exec`, `shutdownStorage`, etc.
        The base class `Config.initialize` handles `_region`, but OpenWhisk doesn't use region.

        :param cfg: Config object to initialize (cast to OpenWhiskConfig).
        :param dct: Dictionary containing OpenWhisk configuration values.
        """
        ow_cfg = cast(OpenWhiskConfig, cfg)
        # Call super to handle common parts like region, though OpenWhisk might not use it.
        super(OpenWhiskConfig, OpenWhiskConfig).initialize(ow_cfg, dct if 'region' in dct else {'region': ''})
        
        ow_cfg.shutdownStorage = dct.get("shutdownStorage", False)
        ow_cfg.removeCluster = dct.get("removeCluster", False)
        ow_cfg.wsk_exec = dct.get("wskExec", "wsk")
        ow_cfg.wsk_bypass_security = dct.get("wskBypassSecurity", False)
        ow_cfg.experimentalManifest = dct.get("experimentalManifest", False)


    def serialize(self) -> dict:
        """
        Serialize OpenWhiskConfig to a dictionary.

        :return: Dictionary representation of OpenWhiskConfig.
        """
        return {
            "name": "openwhisk",
            "region": self._region, # Region is from base, may be empty
            "shutdownStorage": self.shutdownStorage,
            "removeCluster": self.removeCluster,
            "wskExec": self.wsk_exec,
            "wskBypassSecurity": self.wsk_bypass_security,
            "experimentalManifest": self.experimentalManifest,
            "credentials": self._credentials.serialize(), # Empty dict
            "resources": self._resources.serialize(),
        }

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Config:
        """
        Deserialize an OpenWhiskConfig object.

        Populates settings from `config` (user input) and `cached_config` (if any).
        Resources are deserialized separately.

        :param config: User-provided configuration dictionary for OpenWhisk.
        :param cache: Cache client instance.
        :param handlers: Logging handlers.
        :return: An OpenWhiskConfig instance.
        """
        cached_config = cache.get_config("openwhisk") # Entire 'openwhisk' section from cache
        
        # Create config object using user config first, then apply cache for some parts.
        # If cached_config exists, it means some settings might have been persisted.
        # We need to decide the override order: user_config > cached_config or vice-versa for some fields.
        # Typically, user_config for settings like wskExec should override cache.
        # Resources are handled by OpenWhiskResources.deserialize which has its own cache logic.
        
        # Use user 'config' for primary values, provide 'cached_config' for resource deserialization if needed.
        config_to_init_with = {** (cached_config or {}), **config}


        ow_config_obj = OpenWhiskConfig(config_to_init_with, cache) # Pass relevant dict
        ow_config_obj.logging_handlers = handlers

        # Resources deserialization needs careful handling of what 'config' it gets.
        # It should get the 'resources' part of the user config and the 'openwhisk' cache.
        user_resources_config = config.get("resources", {})
        ow_config_obj._resources = cast(
            OpenWhiskResources, OpenWhiskResources.deserialize(user_resources_config, cache, handlers)
        )
        
        # Initialize other fields from combined config (user config takes precedence)
        OpenWhiskConfig.initialize(ow_config_obj, config_to_init_with)
        
        return ow_config_obj

    def update_cache(self, cache: Cache):
        """
        Update the cache with OpenWhiskConfig details.

        Saves settings like `wskExec`, `shutdownStorage`, etc., and calls
        `resources.update_cache` for resource-specific details.

        :param cache: Cache object.
        """
        # Base config like region (if used by OpenWhisk conceptually)
        super().update_cache(cache)
        
        cache.update_config(val=self.shutdownStorage, keys=["openwhisk", "shutdownStorage"])
        cache.update_config(val=self.removeCluster, keys=["openwhisk", "removeCluster"])
        cache.update_config(val=self.wsk_exec, keys=["openwhisk", "wskExec"])
        cache.update_config(val=self.wsk_bypass_security, keys=["openwhisk", "wskBypassSecurity"])
        cache.update_config(
            val=self.experimentalManifest, keys=["openwhisk", "experimentalManifest"]
        )
        # Credentials for OpenWhisk are typically empty, so no specific cache update needed beyond base.
        # self.credentials.update_cache(cache) # Would call empty update_cache if not overridden
        self.resources.update_cache(cache)
