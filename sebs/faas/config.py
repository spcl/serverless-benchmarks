from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from enum import Enum
from typing import Dict, Optional

from sebs.cache import Cache
from sebs.utils import has_platform, LoggingBase, LoggingHandlers

# FIXME: Replace type hints for static generators after migration to 3.7
# https://stackoverflow.com/questions/33533148/how-do-i-specify-that-the-return-type-of-a-method-is-the-same-as-the-class-itsel

"""
Abstract base classes for FaaS system configurations, credentials, and resources.

This module defines the structure for managing FaaS provider-specific details,
including authorization, allocated cloud resources (like storage buckets, IAM roles),
and general deployment settings.
"""


class Credentials(ABC, LoggingBase):
    """
    Abstract base class for FaaS system credentials.

    Credentials are used to authorize operations on functions and other resources.
    The typical order of initialization is:
    1. Load credentials from cache.
    2. Override cached values with any new values provided in the configuration.
    3. If nothing is provided, attempt to initialize using environment variables.
    4. Report failure if no credential information can be found.
    """
    def __init__(self):
        """Initialize a new Credentials object."""
        super().__init__()

    @staticmethod
    @abstractmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> "Credentials":
        """
        Deserialize credentials from a dictionary, potentially using cached values.

        Implementations should handle merging provided configuration with cached data
        and falling back to environment variables if necessary.

        :param config: Dictionary containing credential information.
        :param cache: Cache object for retrieving cached credentials.
        :param handlers: Logging handlers.
        :return: An instance of a Credentials subclass.
        """
        pass

    @abstractmethod
    def serialize(self) -> dict:
        """
        Serialize credentials to a dictionary for storage in cache.

        :return: A dictionary representation of the credentials.
        """
        pass


class Resources(ABC, LoggingBase):
    """
    Abstract base class for managing resources allocated on a FaaS system.

    This includes resources like IAM roles, API Gateways for HTTP triggers,
    and storage buckets. Storage resources (buckets) are specifically managed here.
    """
    class StorageBucketType(str, Enum):
        """Enumeration for types of storage buckets used by SeBS."""
        DEPLOYMENT = "deployment"
        BENCHMARKS = "benchmarks"
        EXPERIMENTS = "experiments"

        @staticmethod
        def deserialize(val: str) -> Resources.StorageBucketType:
            """
            Deserialize a string value to a StorageBucketType enum member.

            :param val: The string value of the bucket type (e.g., "deployment").
            :return: The corresponding StorageBucketType enum member.
            :raises Exception: If the value does not match any known bucket type.
            """
            for member in Resources.StorageBucketType:
                if member.value == val:
                    return member
            raise Exception(f"Unknown storage bucket type type {val}")

    def __init__(self, name: str):
        """
        Initialize a new Resources object.

        :param name: The name of the FaaS provider (e.g., "aws", "azure").
        """
        super().__init__()
        self._name = name
        self._buckets: Dict[Resources.StorageBucketType, str] = {}
        self._resources_id: Optional[str] = None
        self._region: Optional[str] = None # Added to store region

    @property
    def resources_id(self) -> str:
        """A unique identifier for this set of resources."""
        assert self._resources_id is not None, "Resources ID not set!"
        return self._resources_id

    @resources_id.setter
    def resources_id(self, resources_id: str):
        """Set the unique identifier for these resources."""
        self._resources_id = resources_id

    @property
    def has_resources_id(self) -> bool:
        """Check if a resource ID has been set."""
        return self._resources_id is not None

    @property
    def region(self) -> str:
        """The cloud region where these resources are located."""
        assert self._region is not None, "Region not set for resources!"
        return self._region

    @region.setter
    def region(self, region: str):
        """Set the cloud region for these resources."""
        self._region = region

    def get_storage_bucket(self, bucket_type: Resources.StorageBucketType) -> Optional[str]:
        """
        Get the name of a specific type of storage bucket.

        :param bucket_type: The type of the bucket (DEPLOYMENT, BENCHMARKS, EXPERIMENTS).
        :return: The bucket name if set, otherwise None.
        """
        return self._buckets.get(bucket_type)

    def get_storage_bucket_name(self, bucket_type: Resources.StorageBucketType) -> str:
        """
        Generate the expected name for a storage bucket of a given type.

        The name is typically in the format "sebs-{bucket_type_value}-{resources_id}".

        :param bucket_type: The type of the bucket.
        :return: The generated bucket name.
        """
        return f"sebs-{bucket_type.value}-{self.resources_id}"

    def set_storage_bucket(self, bucket_type: Resources.StorageBucketType, bucket_name: str):
        """
        Set the name for a specific type of storage bucket.

        :param bucket_type: The type of the bucket.
        :param bucket_name: The actual name of the bucket in the cloud storage.
        """
        self._buckets[bucket_type] = bucket_name

    @staticmethod
    @abstractmethod
    def initialize(res: Resources, dct: dict):
        """
        Initialize resource attributes from a dictionary (typically from cache or config).

        Subclasses should call `super().initialize(res, dct)` if they override this.
        This base implementation handles `resources_id` and `storage_buckets`.

        :param res: The Resources instance to initialize.
        :param dct: Dictionary containing resource configurations.
        """
        if "resources_id" in dct:
            res.resources_id = dct["resources_id"] # Use setter for potential validation

        if "storage_buckets" in dct:
            for key, value in dct["storage_buckets"].items():
                res.set_storage_bucket(Resources.StorageBucketType.deserialize(key), value)

    @staticmethod
    @abstractmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> "Resources":
        """
        Deserialize a Resources object from a dictionary.

        Implementations should handle provider-specific resource details.

        :param config: Dictionary containing resource information.
        :param cache: Cache object.
        :param handlers: Logging handlers.
        :return: An instance of a Resources subclass.
        """
        pass

    @abstractmethod
    def serialize(self) -> dict:
        """
        Serialize resources to a dictionary for storage in cache.

        Subclasses should call `super().serialize()` and extend the dictionary.
        This base implementation serializes `resources_id` and `storage_buckets`.

        :return: A dictionary representation of the resources.
        """
        out = {}
        if self.has_resources_id:
            out["resources_id"] = self.resources_id
        # Serialize buckets using their string value as key
        out["storage_buckets"] = {key.value: value for key, value in self._buckets.items()}
        return out

    def update_cache(self, cache: Cache):
        """
        Update the cache with the current resource configurations.

        Saves `resources_id` and storage bucket names.

        :param cache: Cache object.
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
    """
    Abstract base class for FaaS system configurations.

    Defines the structure for cloud region, credentials, and allocated resources.
    """
    _region: str

    def __init__(self, name: str):
        """
        Initialize a new FaaS system Config.

        :param name: The name of the FaaS provider (e.g., "aws", "azure").
        """
        super().__init__()
        self._region = ""
        self._name = name

    @property
    def region(self) -> str:
        """The cloud region for the FaaS deployment (e.g., "us-east-1")."""
        return self._region

    @property
    @abstractmethod
    def credentials(self) -> Credentials:
        """The credentials for accessing the FaaS system."""
        pass

    @property
    @abstractmethod
    def resources(self) -> Resources:
        """The resources allocated on the FaaS system."""
        pass

    @staticmethod
    @abstractmethod
    def initialize(cfg: Config, dct: dict):
        """
        Initialize config attributes from a dictionary.

        Subclasses should call `super().initialize(cfg, dct)` if they override this.
        This base implementation initializes the `_region`.

        :param cfg: The Config instance to initialize.
        :param dct: Dictionary containing configuration values.
        """
        cfg._region = dct["region"]

    @staticmethod
    @abstractmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Config:
        """
        Deserialize a Config object from a dictionary, dispatching to the correct subclass.

        Determines the FaaS provider from the 'name' field in the config and calls
        the appropriate subclass's deserialize method.

        :param config: Dictionary containing the FaaS system configuration.
                       Expected to have a 'name' field indicating the provider.
        :param cache: Cache object.
        :param handlers: Logging handlers.
        :return: An instance of a Config subclass.
        :raises AssertionError: If the FaaS provider name is unknown.
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
        assert func, f"Unknown config type: {name}!"
        # Pass the provider-specific part of the config, or the whole thing if not nested
        provider_config = config.get(name, config)
        return func(provider_config, cache, handlers)

    @abstractmethod
    def serialize(self) -> dict:
        """
        Serialize the FaaS system configuration to a dictionary.

        Subclasses should call `super().serialize()` and extend the dictionary.
        This base implementation serializes `name` and `region`.

        :return: A dictionary representation of the configuration.
        """
        return {"name": self._name, "region": self._region}

    @abstractmethod
    def update_cache(self, cache: Cache):
        """
        Update the cache with the current FaaS system configuration.

        Subclasses should call `super().update_cache(cache)`.
        This base implementation updates the `region`.

        :param cache: Cache object.
        """
        cache.update_config(val=self.region, keys=[self._name, "region"])
