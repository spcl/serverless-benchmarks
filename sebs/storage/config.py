"""Configuration classes for storage backends in the Serverless Benchmarking Suite.

This module provides dataclass-based configuration objects for different storage
backends supported by SeBS. It includes abstract base classes that define the
interface for storage configurations, as well as concrete implementations for
specific storage systems.

Key Classes:
    PersistentStorageConfig: Abstract base for object storage configurations
    MinioConfig: Configuration for MinIO S3-compatible object storage
    NoSQLStorageConfig: Abstract base for NoSQL database configurations
    ScyllaDBConfig: Configuration for ScyllaDB DynamoDB-compatible storage

All configuration classes support serialization/deserialization for caching
and provide environment variable mappings for runtime configuration.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List

from sebs.cache import Cache


@dataclass
class PersistentStorageConfig(ABC):
    """Abstract base class for persistent object storage configuration.

    This class defines the interface that all object storage configurations
    must implement. It provides methods for serialization and environment
    variable generation that are used for caching and runtime configuration.

    Subclasses must implement:
        - serialize(): Convert configuration to dictionary for caching
        - envs(): Generate environment variables for benchmark runtime
    """

    @abstractmethod
    def serialize(self) -> Dict[str, Any]:
        """Serialize the configuration to a dictionary.

        Returns:
            Dict[str, Any]: Serialized configuration data suitable for JSON storage
        """
        pass

    @abstractmethod
    def envs(self) -> Dict[str, str]:
        """Generate environment variables for the storage configuration.

        Returns:
            Dict[str, str]: Environment variables to be set in benchmark runtime
        """
        pass


@dataclass
class MinioConfig(PersistentStorageConfig):
    """Configuration for MinIO S3-compatible object storage.

    MinIO provides a local S3-compatible object storage service that runs in
    a Docker container. This configuration class stores all the necessary
    parameters for deploying and connecting to a MinIO instance.

    Attributes:
        address: Network address where MinIO is accessible (auto-detected)
        mapped_port: Host port mapped to MinIO's internal port 9000
        access_key: Access key for MinIO authentication (auto-generated)
        secret_key: Secret key for MinIO authentication (auto-generated)
        instance_id: Docker container ID of the running MinIO instance
        output_buckets: List of bucket names used for benchmark output
        input_buckets: List of bucket names used for benchmark input
        version: MinIO Docker image version to use
        data_volume: Host directory path for persistent data storage
        type: Storage type identifier (always "minio")
    """

    address: str = ""
    mapped_port: int = -1
    access_key: str = ""
    secret_key: str = ""
    instance_id: str = ""
    output_buckets: List[str] = field(default_factory=list)
    input_buckets: List[str] = field(default_factory=lambda: [])
    version: str = ""
    data_volume: str = ""
    type: str = "minio"

    def update_cache(self, path: List[str], cache: Cache) -> None:
        """Update the cache with this configuration's values.

        Stores all configuration fields in the cache using the specified path
        as a prefix. This allows the configuration to be restored later from
        the cache.

        Args:
            path: Cache key path prefix for this configuration
            cache: Cache instance to store configuration in
        """
        for key in MinioConfig.__dataclass_fields__.keys():
            if key == "resources":
                continue
            cache.update_config(val=getattr(self, key), keys=[*path, key])

    @staticmethod
    def deserialize(data: Dict[str, Any]) -> "MinioConfig":
        """Deserialize configuration from a dictionary.

        Creates a new MinioConfig instance from dictionary data, typically
        loaded from cache or configuration files. Only known configuration
        fields are used, unknown fields are ignored.

        Args:
            data: Dictionary containing configuration data

        Returns:
            MinioConfig: New configuration instance
        """
        keys = list(MinioConfig.__dataclass_fields__.keys())
        data = {k: v for k, v in data.items() if k in keys}

        cfg = MinioConfig(**data)

        return cfg

    def serialize(self) -> Dict[str, Any]:
        """Serialize the configuration to a dictionary.

        Returns:
            Dict[str, Any]: All configuration fields as a dictionary
        """
        return self.__dict__

    def envs(self) -> Dict[str, str]:
        """Generate environment variables for MinIO configuration.

        Creates environment variables that can be used by benchmark functions
        to connect to the MinIO storage instance.

        Returns:
            Dict[str, str]: Environment variables for MinIO connection
        """
        return {
            "MINIO_ADDRESS": self.address,
            "MINIO_ACCESS_KEY": self.access_key,
            "MINIO_SECRET_KEY": self.secret_key,
        }


@dataclass
class NoSQLStorageConfig(ABC):
    """Abstract base class for NoSQL database storage configuration.

    This class defines the interface that all NoSQL storage configurations
    must implement. It provides serialization methods used for caching
    and configuration management.

    Subclasses must implement:
        - serialize(): Convert configuration to dictionary for caching
    """

    @abstractmethod
    def serialize(self) -> Dict[str, Any]:
        """Serialize the configuration to a dictionary.

        Returns:
            Dict[str, Any]: Serialized configuration data suitable for JSON storage
        """
        pass


@dataclass
class ScyllaDBConfig(NoSQLStorageConfig):
    """Configuration for ScyllaDB DynamoDB-compatible NoSQL storage.

    ScyllaDB provides a high-performance NoSQL database with DynamoDB-compatible
    API through its Alternator interface. This configuration class stores all
    the necessary parameters for deploying and connecting to a ScyllaDB instance.

    Attributes:
        address: Network address where ScyllaDB is accessible (auto-detected)
        mapped_port: Host port mapped to ScyllaDB's Alternator port
        alternator_port: Internal port for DynamoDB-compatible API (default: 8000)
        access_key: Access key for DynamoDB API (placeholder value)
        secret_key: Secret key for DynamoDB API (placeholder value)
        instance_id: Docker container ID of the running ScyllaDB instance
        region: AWS region placeholder (not used for local deployment)
        cpus: Number of CPU cores allocated to ScyllaDB container
        memory: Memory allocation in MB for ScyllaDB container
        version: ScyllaDB Docker image version to use
        data_volume: Host directory path for persistent data storage
    """

    address: str = ""
    mapped_port: int = -1
    alternator_port: int = 8000
    access_key: str = "None"
    secret_key: str = "None"
    instance_id: str = ""
    region: str = "None"
    cpus: int = -1
    memory: int = -1
    version: str = ""
    data_volume: str = ""

    def update_cache(self, path: List[str], cache: Cache) -> None:
        """Update the cache with this configuration's values.

        Stores all configuration fields in the cache using the specified path
        as a prefix. This allows the configuration to be restored later from
        the cache.

        Args:
            path: Cache key path prefix for this configuration
            cache: Cache instance to store configuration in
        """
        for key in ScyllaDBConfig.__dataclass_fields__.keys():
            cache.update_config(val=getattr(self, key), keys=[*path, key])

    @staticmethod
    def deserialize(data: Dict[str, Any]) -> "ScyllaDBConfig":
        """Deserialize configuration from a dictionary.

        Creates a new ScyllaDBConfig instance from dictionary data, typically
        loaded from cache or configuration files. Only known configuration
        fields are used, unknown fields are ignored.

        Args:
            data: Dictionary containing configuration data

        Returns:
            ScyllaDBConfig: New configuration instance
        """
        keys = list(ScyllaDBConfig.__dataclass_fields__.keys())
        data = {k: v for k, v in data.items() if k in keys}

        cfg = ScyllaDBConfig(**data)

        return cfg

    def serialize(self) -> Dict[str, Any]:
        """Serialize the configuration to a dictionary.

        Returns:
            Dict[str, Any]: All configuration fields as a dictionary
        """
        return self.__dict__
