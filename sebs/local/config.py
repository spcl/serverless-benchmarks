"""Configuration classes for the local execution platform.

This module provides configuration classes for the SeBS local execution platform,
including credentials, resources, and overall configuration management. The local
platform requires minimal configuration since it runs functions locally using
Docker containers.

Classes:
    LocalCredentials: Empty credentials class for local execution
    LocalResources: Resource management for local deployments
    LocalConfig: Main configuration class for local platform
"""

from typing import cast, Optional, Set

from sebs.cache import Cache
from sebs.faas.config import Config, Credentials, Resources
from sebs.storage.resources import SelfHostedResources
from sebs.storage.config import NoSQLStorageConfig, PersistentStorageConfig
from sebs.utils import LoggingHandlers


class LocalCredentials(Credentials):
    """Credentials class for local execution platform.
    
    The local platform doesn't require any authentication credentials since
    functions run locally using Docker containers. This class provides the
    required interface with empty implementations.
    """
    
    def serialize(self) -> dict:
        """Serialize credentials to dictionary.
        
        Returns:
            dict: Empty dictionary as no credentials are required for local execution
        """
        return {}

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Credentials:
        """Deserialize credentials from configuration.
        
        Args:
            config: Configuration dictionary (unused for local)
            cache: Cache client (unused for local) 
            handlers: Logging handlers (unused for local)
            
        Returns:
            LocalCredentials: New instance of local credentials
        """
        return LocalCredentials()


"""
    No need to cache and store - we prepare the benchmark and finish.
    The rest is used later by the user.
"""


class LocalResources(SelfHostedResources):
    """Resource management for local execution platform.
    
    Manages resources for local function execution, including port allocation
    for Docker containers and storage configurations. Tracks allocated ports
    to avoid conflicts when running multiple functions.
    
    Attributes:
        _path: Path for local resource storage
        _allocated_ports: Set of ports currently allocated to containers
    """
    
    def __init__(
        self,
        storage_cfg: Optional[PersistentStorageConfig] = None,
        nosql_storage_cfg: Optional[NoSQLStorageConfig] = None,
    ):
        """Initialize local resources.
        
        Args:
            storage_cfg: Optional persistent storage configuration
            nosql_storage_cfg: Optional NoSQL storage configuration
        """
        self._path: str = ""
        super().__init__("local", storage_cfg, nosql_storage_cfg)
        self._allocated_ports: Set[int] = set()

    @property
    def allocated_ports(self) -> set:
        """Get the set of allocated ports.
        
        Returns:
            set: Set of port numbers currently allocated to containers
        """
        return self._allocated_ports

    def serialize(self) -> dict:
        """Serialize resources to dictionary.
        
        Returns:
            dict: Dictionary containing resource configuration including allocated ports
        """
        out = super().serialize()

        out["allocated_ports"] = list(self._allocated_ports)
        return out

    @staticmethod
    def initialize(res: Resources, config: dict) -> None:
        """Initialize resources from configuration.
        
        Args:
            res: Resources instance to initialize
            config: Configuration dictionary containing resource settings
        """
        resources = cast(LocalResources, res)

        if "allocated_ports" in config:
            resources._allocated_ports = set(config["allocated_ports"])

    def update_cache(self, cache: Cache) -> None:
        """Update cache with current resource state.
        
        Args:
            cache: Cache client to update
        """
        super().update_cache(cache)
        cache.update_config(
            val=list(self._allocated_ports), keys=["local", "resources", "allocated_ports"]
        )

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Resources:
        """Deserialize resources from configuration.
        
        Args:
            config: Configuration dictionary
            cache: Cache client for loading cached resources
            handlers: Logging handlers for resource logging
            
        Returns:
            LocalResources: Initialized local resources instance
        """
        ret = LocalResources()

        cached_config = cache.get_config("local")
        ret._deserialize(ret, config, cached_config)

        # Load cached values
        if cached_config and "resources" in cached_config:
            LocalResources.initialize(ret, cached_config["resources"])
            ret.logging_handlers = handlers
            ret.logging.info("Using cached resources for Local")
        else:
            # Check for new config
            ret.logging_handlers = handlers
            LocalResources.initialize(ret, config)

        return ret


class LocalConfig(Config):
    """Configuration class for local execution platform.
    
    Provides the main configuration interface for the local platform,
    combining credentials and resources. The local platform requires
    minimal configuration since it runs functions locally.
    
    Attributes:
        _credentials: Local credentials instance (empty)
        _resources: Local resources instance for port management
    """
    
    def __init__(self):
        """Initialize local configuration."""
        super().__init__(name="local")
        self._credentials = LocalCredentials()
        self._resources = LocalResources()

    @staticmethod
    def typename() -> str:
        """Get the type name for this configuration.
        
        Returns:
            str: Type name "Local.Config"
        """
        return "Local.Config"

    @staticmethod
    def initialize(cfg: Config, dct: dict) -> None:
        """Initialize configuration from dictionary.
        
        Args:
            cfg: Configuration instance to initialize
            dct: Dictionary containing configuration data
            
        Note:
            No initialization needed for local platform
        """
        pass

    @property
    def credentials(self) -> LocalCredentials:
        """Get the local credentials.
        
        Returns:
            LocalCredentials: The credentials instance
        """
        return self._credentials

    @property
    def resources(self) -> LocalResources:
        """Get the local resources.
        
        Returns:
            LocalResources: The resources instance
        """
        return self._resources

    @resources.setter
    def resources(self, val: LocalResources) -> None:
        """Set the local resources.
        
        Args:
            val: New resources instance
        """
        self._resources = val

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Config:
        """Deserialize configuration from dictionary.
        
        Args:
            config: Configuration dictionary
            cache: Cache client for loading cached configuration
            handlers: Logging handlers for configuration logging
            
        Returns:
            LocalConfig: Initialized local configuration instance
        """
        config_obj = LocalConfig()
        config_obj.resources = cast(
            LocalResources, LocalResources.deserialize(config, cache, handlers)
        )
        config_obj.logging_handlers = handlers
        return config_obj

    def serialize(self) -> dict:
        """Serialize configuration to dictionary.
        
        Returns:
            dict: Dictionary containing configuration data
        """
        out = {"name": "local", "region": self._region, "resources": self._resources.serialize()}
        return out

    def update_cache(self, cache: Cache) -> None:
        """Update cache with current configuration.
        
        Args:
            cache: Cache client to update
        """
        self.resources.update_cache(cache)
