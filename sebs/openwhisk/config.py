"""
Configuration management for Apache OpenWhisk deployments in SeBS.

This module provides configuration classes for managing OpenWhisk-specific settings,
credentials, and resources. It handles Docker registry configuration, storage settings,
and deployment parameters for OpenWhisk serverless functions.

Classes:
    OpenWhiskCredentials: Manages authentication credentials for OpenWhisk
    OpenWhiskResources: Handles Docker registry and storage resources
    OpenWhiskConfig: Main configuration class for OpenWhisk deployment settings
"""

from __future__ import annotations

from typing import Optional, cast, Dict, Any

from sebs.cache import Cache
from sebs.faas.config import Credentials, Resources, Config
from sebs.utils import LoggingHandlers
from sebs.storage.resources import SelfHostedResources


class OpenWhiskCredentials(Credentials):
    """
    Manages authentication credentials for OpenWhisk deployments.

    This class handles credential serialization and deserialization for OpenWhisk
    platforms. Currently implements a minimal credential system.

    Note:
        OpenWhisk deployments typically rely on local authentication through
        the wsk CLI tool rather than explicit credential management.
    """

    @staticmethod
    def deserialize(config: Dict[str, Any], cache: Cache, handlers: LoggingHandlers) -> Credentials:
        """
        Deserialize OpenWhisk credentials from configuration.

        Args:
            config: Configuration dictionary containing credential data
            cache: Cache instance for storing/retrieving cached credentials
            handlers: Logging handlers for credential operations

        Returns:
            OpenWhiskCredentials instance (currently empty)
        """
        return OpenWhiskCredentials()

    def serialize(self) -> Dict[str, Any]:
        """
        Serialize credentials to dictionary format.

        Returns:
            Empty dictionary as OpenWhisk uses CLI-based authentication
        """
        return {}


class OpenWhiskResources(SelfHostedResources):
    """
    Manages Docker registry and storage resources for OpenWhisk deployments.

    This class handles configuration of Docker registries, authentication credentials,
    and storage resources needed for OpenWhisk function deployments. It supports
    both user-provided and cached configurations.

    Attributes:
        _docker_registry: Docker registry URL for storing function images
        _docker_username: Username for Docker registry authentication
        _docker_password: Password for Docker registry authentication
        _registry_updated: Flag indicating if registry configuration has been updated
        _storage_updated: Flag indicating if storage configuration has been updated
    """

    def __init__(
        self,
        registry: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        registry_updated: bool = False,
    ) -> None:
        """
        Initialize OpenWhisk resources configuration.

        Args:
            registry: Docker registry URL for storing function images
            username: Username for Docker registry authentication
            password: Password for Docker registry authentication
            registry_updated: Whether registry configuration has been updated
        """
        super().__init__(name="openwhisk")
        self._docker_registry = registry if registry != "" else None
        self._docker_username = username if username != "" else None
        self._docker_password = password if password != "" else None
        self._registry_updated = registry_updated
        self._storage_updated = False

    @staticmethod
    def typename() -> str:
        """
        Get the type name for this resource class.

        Returns:
            String identifier for OpenWhisk resources
        """
        return "OpenWhisk.Resources"

    @property
    def docker_registry(self) -> Optional[str]:
        """
        Get the Docker registry URL.

        Returns:
            Docker registry URL or None if not configured
        """
        return self._docker_registry

    @property
    def docker_username(self) -> Optional[str]:
        """
        Get the Docker registry username.

        Returns:
            Docker registry username or None if not configured
        """
        return self._docker_username

    @property
    def docker_password(self) -> Optional[str]:
        """
        Get the Docker registry password.

        Returns:
            Docker registry password or None if not configured
        """
        return self._docker_password

    @property
    def storage_updated(self) -> bool:
        """
        Check if storage configuration has been updated.

        Returns:
            True if storage configuration has been updated, False otherwise
        """
        return self._storage_updated

    @property
    def registry_updated(self) -> bool:
        """
        Check if registry configuration has been updated.

        Returns:
            True if registry configuration has been updated, False otherwise
        """
        return self._registry_updated

    @staticmethod
    def initialize(res: Resources, dct: Dict[str, Any]) -> None:
        """
        Initialize OpenWhisk resources from dictionary configuration.

        Args:
            res: Resources instance to initialize
            dct: Dictionary containing Docker registry configuration
                Expected keys: 'registry', 'username', 'password'
        """
        ret = cast(OpenWhiskResources, res)
        ret._docker_registry = dct["registry"]
        ret._docker_username = dct["username"]
        ret._docker_password = dct["password"]

    @staticmethod
    def deserialize(config: Dict[str, Any], cache: Cache, handlers: LoggingHandlers) -> Resources:
        """
        Deserialize OpenWhisk resources from configuration.

        This method handles both user-provided configuration and cached values,
        prioritizing user configuration while detecting updates.

        Args:
            config: Configuration dictionary that may contain 'docker_registry' section
            cache: Cache instance to retrieve/store configuration
            handlers: Logging handlers for resource operations

        Returns:
            OpenWhiskResources instance with appropriate configuration
        """
        cached_config = cache.get_config("openwhisk")
        ret = OpenWhiskResources()
        if cached_config:
            super(OpenWhiskResources, OpenWhiskResources).initialize(
                ret, cached_config["resources"]
            )

        ret._deserialize(ret, config, cached_config)

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

        return ret

    def update_cache(self, cache: Cache) -> None:
        """
        Update cache with current resource configuration.

        Args:
            cache: Cache instance to update with current configuration
        """
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

    def serialize(self) -> Dict[str, Any]:
        """
        Serialize resource configuration to dictionary.

        Returns:
            Dictionary containing all resource configuration including
            Docker registry settings and inherited storage configuration
        """
        out: Dict[str, Any] = {
            **super().serialize(),
            "docker_registry": self.docker_registry,
            "docker_username": self.docker_username,
            "docker_password": self.docker_password,
        }
        return out


class OpenWhiskConfig(Config):
    """
    Main configuration class for OpenWhisk deployments.

    This class manages all OpenWhisk-specific configuration settings including
    cluster management, WSK CLI settings, and experimental features. It integrates
    with the broader SeBS configuration system.

    Attributes:
        name: Platform name identifier ('openwhisk')
        shutdownStorage: Whether to shutdown storage after experiments
        removeCluster: Whether to remove cluster after experiments
        wsk_exec: Path to WSK CLI executable
        wsk_bypass_security: Whether to bypass security checks in WSK CLI
        experimentalManifest: Whether to use experimental manifest features
        cache: Cache instance for configuration persistence
        _credentials: OpenWhisk credentials configuration
        _resources: OpenWhisk resources configuration
    """

    name: str
    shutdownStorage: bool
    removeCluster: bool
    wsk_exec: str
    wsk_bypass_security: bool
    experimentalManifest: bool
    cache: Cache

    def __init__(self, config: Dict[str, Any], cache: Cache) -> None:
        """
        Initialize OpenWhisk configuration.

        Args:
            config: Configuration dictionary containing OpenWhisk settings
            cache: Cache instance for configuration persistence
        """
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
        """
        Get OpenWhisk credentials configuration.

        Returns:
            OpenWhiskCredentials instance
        """
        return self._credentials

    @property
    def resources(self) -> OpenWhiskResources:
        """
        Get OpenWhisk resources configuration.

        Returns:
            OpenWhiskResources instance
        """
        return self._resources

    @staticmethod
    def initialize(cfg: Config, dct: Dict[str, Any]) -> None:
        """
        Initialize configuration from dictionary (currently no-op).

        Args:
            cfg: Configuration instance to initialize
            dct: Dictionary containing initialization data
        """
        pass

    def serialize(self) -> Dict[str, Any]:
        """
        Serialize configuration to dictionary format.

        Returns:
            Dictionary containing all OpenWhisk configuration settings
            including credentials and resources
        """
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
    def deserialize(config: Dict[str, Any], cache: Cache, handlers: LoggingHandlers) -> Config:
        """
        Deserialize OpenWhisk configuration from dictionary and cache.

        Args:
            config: Configuration dictionary containing OpenWhisk settings
            cache: Cache instance to retrieve cached configuration
            handlers: Logging handlers for configuration operations

        Returns:
            OpenWhiskConfig instance with deserialized configuration
        """
        cached_config = cache.get_config("openwhisk")
        resources = cast(
            OpenWhiskResources, OpenWhiskResources.deserialize(config, cache, handlers)
        )

        res = OpenWhiskConfig(config, cached_config)
        res.logging_handlers = handlers
        res._resources = resources
        return res

    def update_cache(self, cache: Cache) -> None:
        """
        Update cache with current configuration values.

        Args:
            cache: Cache instance to update with current configuration
        """
        cache.update_config(val=self.shutdownStorage, keys=["openwhisk", "shutdownStorage"])
        cache.update_config(val=self.removeCluster, keys=["openwhisk", "removeCluster"])
        cache.update_config(val=self.wsk_exec, keys=["openwhisk", "wskExec"])
        cache.update_config(val=self.wsk_bypass_security, keys=["openwhisk", "wskBypassSecurity"])
        cache.update_config(
            val=self.experimentalManifest, keys=["openwhisk", "experimentalManifest"]
        )
        self.resources.update_cache(cache)
