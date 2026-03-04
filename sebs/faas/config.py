"""Configuration management for Function-as-a-Service (FaaS) systems.

This module provides abstract base classes for managing configurations across
different FaaS platforms (AWS Lambda, Azure Functions, Google Cloud Functions,
OpenWhisk, etc.). It defines the core interfaces for:

- Credentials management and authentication
- Resource allocation and management
- Platform-specific configuration settings
- Configuration serialization and caching

The module follows a hierarchical structure where each platform implements these
abstract classes with their specific authentication methods, resource types,
and configuration parameters. All configurations support caching to avoid
repeated initialization and provide persistence across benchmark runs.

Classes:
    Credentials: Abstract base for platform authentication credentials
    Resources: Abstract base for cloud resource management
    Config: Abstract base for complete platform configuration

The credentials initialization follows this precedence order:
1. Load credentials with values provided in config
2. Fall back to environment variables
3. Report failure if no credentials are available
"""

from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from enum import Enum
from typing import Dict, Optional

from sebs.cache import Cache
from sebs.utils import has_platform, LoggingBase, LoggingHandlers


class Credentials(ABC, LoggingBase):
    """Abstract base class for FaaS platform authentication credentials.

    This class defines the interface for managing authentication credentials
    across different FaaS platforms. Each platform implementation provides
    specific credential types (API keys, service account files, connection
    strings, etc.) while following the common serialization and caching
    patterns defined here.
    """

    def __init__(self):
        """Initialize the credentials base class with logging support."""
        super().__init__()

    @staticmethod
    @abstractmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> "Credentials":
        """Create credentials instance from user config and cached values.

        This method implements the credential loading hierarchy:
        1. Use new config values if provided
        2. Load from environment variables
        3. Fail if no credentials available

        Credentials are NOT cached.

        Args:
            config: User-provided configuration dictionary
            cache: Cache instance for loading stored credentials
            handlers: Logging handlers for error reporting

        Returns:
            Credentials: Platform-specific credentials instance

        Raises:
            RuntimeError: If no valid credentials can be loaded
        """
        pass

    @abstractmethod
    def serialize(self) -> dict:
        """Serialize credentials to dictionary for cache storage.

        Returns:
            dict: Serialized credential data suitable for JSON storage

        Note:
            Implementations should be careful about storing sensitive
            information and may choose to exclude certain fields.
        """
        pass


class Resources(ABC, LoggingBase):
    """Abstract base class for FaaS platform resource management.

    This class manages cloud resources allocated for function execution and
    deployment across different FaaS platforms. Resources include infrastructure
    components like IAM roles, API gateways, networking components, and storage
    buckets needed to support serverless function deployment and execution.

    Storage resources (object storage, NoSQL databases) are handled separately
    through dedicated storage classes, while this class focuses on compute
    and deployment infrastructure.

    Key responsibilities:
    - Resource ID management and generation
    - Storage bucket lifecycle management
    - Platform-specific resource provisioning
    - Resource serialization and caching
    - Resource cleanup and deallocation
    """

    class StorageBucketType(str, Enum):
        """Enumeration of storage bucket types used by SeBS.

        Different bucket types serve different purposes in the benchmarking workflow:
        - DEPLOYMENT: Stores function deployment packages (ZIP files, containers)
        - BENCHMARKS: Stores benchmark input data and test files
        - EXPERIMENTS: Stores experiment results and output data
        """

        DEPLOYMENT = "deployment"
        BENCHMARKS = "benchmarks"
        EXPERIMENTS = "experiments"

        @staticmethod
        def deserialize(val: str) -> "Resources.StorageBucketType":
            """Deserialize a string value to a StorageBucketType enum.

            Args:
                val: String value to convert to enum

            Returns:
                StorageBucketType: Corresponding enum value

            Raises:
                Exception: If the value doesn't match any enum member
            """
            for member in Resources.StorageBucketType:
                if member.value == val:
                    return member
            raise Exception(f"Unknown storage bucket type type {val}")

    def __init__(self, name: str):
        """Initialize the resources base class.

        Args:
            name: Platform name (e.g., 'aws', 'azure', 'gcp')
        """
        super().__init__()
        self._name = name
        self._buckets: Dict[Resources.StorageBucketType, str] = {}
        self._resources_id: Optional[str] = None

    @property
    def resources_id(self) -> str:
        """Get the unique resource ID for this deployment.

        Returns:
            str: Unique resource identifier

        Raises:
            AssertionError: If no resource ID has been set
        """
        assert self._resources_id is not None
        return self._resources_id

    @resources_id.setter
    def resources_id(self, resources_id: str):
        """Set the unique resource ID for this deployment.

        Args:
            resources_id: Unique identifier for resource grouping
        """
        self._resources_id = resources_id

    @property
    def has_resources_id(self) -> bool:
        """Check if a resource ID has been assigned.

        Returns:
            bool: True if resource ID is set, False otherwise
        """
        return self._resources_id is not None

    @property
    def region(self) -> str:
        """Get the cloud region for resource deployment.

        Returns:
            str: Cloud region identifier
        """
        return self._region

    @region.setter
    def region(self, region: str):
        """Set the cloud region for resource deployment.

        Args:
            region: Cloud region identifier
        """
        self._region = region

    def get_storage_bucket(self, bucket_type: Resources.StorageBucketType) -> Optional[str]:
        """Get the bucket name for a specific bucket type.

        Args:
            bucket_type: Type of bucket to retrieve

        Returns:
            Optional[str]: Bucket name if set, None otherwise
        """
        return self._buckets.get(bucket_type)

    def get_storage_bucket_name(self, bucket_type: Resources.StorageBucketType) -> str:
        """Generate a standardized bucket name for a bucket type.

        Creates bucket names following the pattern: sebs-{type}-{resource_id}

        Args:
            bucket_type: Type of bucket to name

        Returns:
            str: Generated bucket name
        """
        return f"sebs-{bucket_type.value}-{self._resources_id}"

    def set_storage_bucket(self, bucket_type: Resources.StorageBucketType, bucket_name: str):
        """Set the bucket name for a specific bucket type.

        Args:
            bucket_type: Type of bucket to set
            bucket_name: Name of the bucket
        """
        self._buckets[bucket_type] = bucket_name

    @staticmethod
    @abstractmethod
    def initialize(res: "Resources", dct: dict):
        """Initialize a Resources instance from configuration dictionary.

        This base implementation handles common resource initialization
        including resource ID and storage bucket configuration. Platform-specific
        implementations should call this method and add their own initialization.

        Args:
            res: Resources instance to initialize
            dct: Configuration dictionary from cache or user config
        """
        if "resources_id" in dct:
            res._resources_id = dct["resources_id"]

        if "storage_buckets" in dct:
            for key, value in dct["storage_buckets"].items():
                res._buckets[Resources.StorageBucketType.deserialize(key)] = value

    @staticmethod
    @abstractmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> "Resources":
        """Create resources instance from user config and cached values.

        Args:
            config: User-provided configuration dictionary
            cache: Cache instance for loading stored resources
            handlers: Logging handlers for error reporting

        Returns:
            Resources: Platform-specific resources instance
        """
        pass

    @abstractmethod
    def serialize(self) -> dict:
        """Serialize resources to dictionary for cache storage.

        Subclasses should call `super().serialize()` and extend the dictionary.
        This base implementation serializes `resources_id` and `storage_buckets`.

        Returns:
            dict: Serialized resource data including resource ID and bucket mappings
        """
        out = {}
        if self.has_resources_id:
            out["resources_id"] = self.resources_id
        for key, value in self._buckets.items():
            out[key.value] = value
        return out

    def update_cache(self, cache: Cache):
        """Update the cache with current resource configuration.

        Stores the resource ID and storage bucket mappings in the cache
        for future retrieval.

        Args:
            cache: Cache instance to update
        """
        if self.has_resources_id:
            cache.update_config(
                val=self.resources_id, keys=[self._name, "resources", "resources_id"]
            )
        for key, value in self._buckets.items():
            cache.update_config(
                val=value, keys=[self._name, "resources", "storage_buckets", key.value]
            )


class Config(ABC, LoggingBase):
    """Abstract base class for complete FaaS platform configuration.

    This class combines credentials and resources into a complete platform
    configuration, along with platform-specific settings like region selection.
    It provides the top-level configuration interface used throughout the
    benchmarking framework.

    The Config class coordinates:
    - Platform credentials for authentication
    - Resource allocation and management
    - Regional deployment settings
    - Configuration persistence and caching
    - Platform-specific parameter handling
    """

    _region: str

    def __init__(self, name: str):
        """Initialize the configuration base class.

        Args:
            name: Platform name (e.g., 'aws', 'azure', 'gcp')
        """
        super().__init__()
        self._region = ""
        self._name = name

    @property
    def region(self) -> str:
        """Get the cloud region for deployment.

        Returns:
            str: Cloud region identifier
        """
        return self._region

    @property
    @abstractmethod
    def credentials(self) -> Credentials:
        """Get the platform credentials.

        Returns:
            Credentials: Platform-specific credentials instance
        """
        pass

    @property
    @abstractmethod
    def resources(self) -> Resources:
        """Get the platform resources.

        Returns:
            Resources: Platform-specific resources instance
        """
        pass

    @staticmethod
    @abstractmethod
    def initialize(cfg: "Config", dct: dict):
        """Initialize a Config instance from configuration dictionary.

        Args:
            cfg: Config instance to initialize
            dct: Configuration dictionary
        """
        cfg._region = dct["region"]

    @staticmethod
    @abstractmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> "Config":
        """Create configuration instance from user config and cached values.

        This method serves as a factory for platform-specific configurations,
        dynamically loading the appropriate implementation based on the platform
        name specified in the configuration. To do that, it calls
        the appropriate subclass's deserialize method.

        Args:
            config: User-provided configuration dictionary
            cache: Cache instance for loading stored configuration
            handlers: Logging handlers for error reporting

        Returns:
            Config: Platform-specific configuration instance

        Raises:
            AssertionError: If the platform type is unknown or unsupported
        """
        from sebs.local.config import LocalConfig

        name = config["name"]
        implementations = {"local": LocalConfig.deserialize}
        if has_platform("aws"):
            from sebs.aws.config import AWSConfig

            implementations["aws"] = AWSConfig.deserialize
        if has_platform("azure"):
            from sebs.azure.config import AzureConfig

            implementations["azure"] = AzureConfig.deserialize
        if has_platform("gcp"):
            from sebs.gcp.config import GCPConfig

            implementations["gcp"] = GCPConfig.deserialize
        if has_platform("openwhisk"):
            from sebs.openwhisk.config import OpenWhiskConfig

            implementations["openwhisk"] = OpenWhiskConfig.deserialize
        func = implementations.get(name)
        assert func, "Unknown config type!"
        return func(config[name] if name in config else config, cache, handlers)

    @abstractmethod
    def serialize(self) -> dict:
        """Serialize configuration to dictionary for cache storage.

        Subclasses should call `super().serialize()` and extend the dictionary.
        This base implementation serializes `name` and `region`.

        Returns:
            dict: Serialized configuration including platform name and region
        """
        return {"name": self._name, "region": self._region}

    @abstractmethod
    def update_cache(self, cache: Cache):
        """Update the cache with current configuration settings.

        Args:
            cache: Cache instance to update
        """
        cache.update_config(val=self.region, keys=[self._name, "region"])
