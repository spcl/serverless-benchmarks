# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
"""Configuration classes for storage backends in the Serverless Benchmarking Suite.

All configuration classes support serialization/deserialization for caching
and provide environment variable mappings for runtime configuration.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Type, TypeVar

from sebs.cache import Cache


@dataclass
class PersistentStorageConfig(ABC):
    """Abstract base class for persistent object storage configuration.

    This class defines the interface that all object storage configurations
    must implement. It provides methods for serialization and environment
    variable generation that are used for caching and runtime configuration.

    This is used by MinioStorage in different deployments.

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
    def envs(self, external: bool = True) -> Dict[str, str]:
        """Generate environment variables for the storage configuration.

        Args:
            external: Advertise the externally reachable address. Functions running
                on the same Docker bridge as the storage (local deployment) must use
                the internal address instead, as Docker does not route traffic from
                the bridge to ports published on the host.

        Returns:
            Dict[str, str]: Environment variables to be set in benchmark runtime
        """
        pass


@dataclass
class S3CompatibleConfig(PersistentStorageConfig):
    """Configuration for self-hosted, S3-compatible object storage.

    The storage runs in a Docker container; see MinioConfig and RustFSConfig
    for the supported implementations. This configuration class stores all the
    necessary parameters for deploying and connecting to the instance.

    Attributes:
        address: Network address used by SeBS itself to reach the storage (auto-detected).
            On Linux this is the container's bridge IP and internal port.
        external_address: Network address advertised to benchmark functions,
            e.g., the host's IP and the mapped port. Functions running outside
            the Docker bridge network (OpenWhisk, Kubernetes) need this address.
            Falls back to `address` when empty.
        mapped_port: Host port mapped to the container's S3 port 9000
        access_key: Access key for authentication (auto-generated)
        secret_key: Secret key for authentication (auto-generated)
        instance_id: Docker container ID of the running instance
        output_buckets: List of bucket names used for benchmark output
        input_buckets: List of bucket names used for benchmark input
        version: Docker image version to use
        data_volume: Host directory or named Docker volume for persistent data storage
        type: Storage type identifier, set by the subclasses
    """

    address: str = ""
    external_address: str = ""
    mapped_port: int = -1
    access_key: str = ""
    secret_key: str = ""
    instance_id: str = ""
    output_buckets: List[str] = field(default_factory=list)
    input_buckets: List[str] = field(default_factory=lambda: [])
    version: str = ""
    data_volume: str = ""
    type: str = ""
    remove_containers: bool = False

    def update_cache(self, path: List[str], cache: Cache) -> None:
        """Update the cache with this configuration's values.

        Stores all configuration fields in the cache using the specified path
        as a prefix. This allows the configuration to be restored later from
        the cache.

        Args:
            path: Cache key path prefix for this configuration
            cache: Cache instance to store configuration in
        """
        for key in self.__dataclass_fields__.keys():
            cache.update_config(val=getattr(self, key), keys=[*path, key])

    T = TypeVar("T", bound="S3CompatibleConfig")

    @classmethod
    def deserialize(cls: Type[T], data: Dict[str, Any]) -> T:
        """Deserialize configuration from a dictionary.

        Creates a new configuration instance from dictionary data, typically
        loaded from cache or configuration files. Only known configuration
        fields are used, unknown fields are ignored.

        Args:
            data: Dictionary containing configuration data

        Returns:
            T: New configuration instance of the calling class
        """
        keys = list(cls.__dataclass_fields__.keys())
        data = {k: v for k, v in data.items() if k in keys}

        return cls(**data)

    def serialize(self) -> Dict[str, Any]:
        """Serialize the configuration to a dictionary.

        Returns:
            Dict[str, Any]: All configuration fields as a dictionary
        """
        return self.__dict__

    def envs(self, external: bool = True) -> Dict[str, str]:
        """Generate environment variables for the storage configuration.

        Creates environment variables that can be used by benchmark functions
        to connect to the storage instance. The variable names are shared by
        all S3-compatible implementations, so function code stays unchanged.

        Args:
            external: Advertise the externally reachable address instead of the
                internal one; see PersistentStorageConfig.envs.

        Returns:
            Dict[str, str]: Environment variables for the storage connection
        """
        return {
            "MINIO_ADDRESS": (self.external_address or self.address) if external else self.address,
            "MINIO_ACCESS_KEY": self.access_key,
            "MINIO_SECRET_KEY": self.secret_key,
        }


@dataclass
class MinioConfig(S3CompatibleConfig):
    """Configuration for MinIO object storage."""

    type: str = "minio"


@dataclass
class RustFSConfig(S3CompatibleConfig):
    """Configuration for RustFS object storage."""

    type: str = "rustfs"


@dataclass
class NoSQLStorageConfig(ABC):
    """Abstract base class for NoSQL database storage configuration.

    This class defines the interface that all NoSQL storage configurations
    must implement. It provides serialization methods used for caching
    and configuration management.

    This class will be overidden by specific implementations for different
    FaaS systems.

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
        address: Network address used by SeBS itself to reach ScyllaDB (auto-detected).
            On Linux this is the container's bridge IP and the Alternator port.
        external_address: Network address advertised to benchmark functions,
            e.g., the host's IP and the mapped port. Falls back to `address` when empty.
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
    external_address: str = ""
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
    remove_containers: bool = False

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
