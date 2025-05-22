from abc import ABC
from abc import abstractmethod
from typing import List

from dataclasses import dataclass, field

from sebs.cache import Cache


@dataclass
class PersistentStorageConfig(ABC):
    """
    Abstract base class for persistent storage configurations.

    Defines the interface for serializing the configuration and providing
    environment variables necessary for functions to access the storage.
    """
    @abstractmethod
    def serialize(self) -> dict:
        """
        Serialize the storage configuration to a dictionary.

        :return: A dictionary representation of the configuration.
        """
        pass

    @abstractmethod
    def envs(self) -> dict:
        """
        Return a dictionary of environment variables required by functions
        to connect to and use this persistent storage.

        :return: Dictionary of environment variables.
        """
        pass


@dataclass
class MinioConfig(PersistentStorageConfig):
    """
    Configuration for a self-hosted Minio S3-compatible object storage.

    Attributes:
        address: Network address of the Minio server.
        mapped_port: Host port mapped to the Minio container's port.
        access_key: Access key for Minio.
        secret_key: Secret key for Minio.
        instance_id: Docker container ID of the running Minio instance.
        output_buckets: List of output bucket names.
        input_buckets: List of input bucket names.
        version: Version of the Minio Docker image.
        data_volume: Name of the Docker volume used for Minio data persistence.
        type: Identifier for this storage type, defaults to "minio".
    """
    address: str = ""
    mapped_port: int = -1
    access_key: str = ""
    secret_key: str = ""
    instance_id: str = ""
    output_buckets: List[str] = field(default_factory=list)
    input_buckets: List[str] = field(default_factory=lambda: []) # Ensure default_factory is callable
    version: str = ""
    data_volume: str = ""
    type: str = "minio" # Type identifier for deserialization or type checking

    def update_cache(self, path: List[str], cache: Cache):
        """
        Update the SeBS cache with the Minio configuration details.

        Iterates over dataclass fields and updates them in the cache under the given path.

        :param path: List of keys defining the path in the cache structure.
        :param cache: The Cache client instance.
        """
        for key_name in self.__dataclass_fields__.keys():
            # Avoid trying to cache complex objects or fields not meant for direct caching
            if key_name == "resources": # Example of a field to skip if it existed
                continue
            cache.update_config(val=getattr(self, key_name), keys=[*path, key_name])
        # If self.resources (from a potential parent or mixed-in class) needed caching:
        # self.resources.update_cache(cache)

    @staticmethod
    def deserialize(data: dict) -> "MinioConfig":
        """
        Deserialize a MinioConfig object from a dictionary.

        Filters the input dictionary to include only known fields of MinioConfig.

        :param data: Dictionary containing MinioConfig data.
        :return: A MinioConfig instance.
        """
        known_keys = list(MinioConfig.__dataclass_fields__.keys())
        filtered_data = {k: v for k, v in data.items() if k in known_keys}
        # Ensure list fields are correctly initialized if missing in filtered_data
        if 'output_buckets' not in filtered_data:
            filtered_data['output_buckets'] = []
        if 'input_buckets' not in filtered_data:
            filtered_data['input_buckets'] = []
        return MinioConfig(**filtered_data)

    def serialize(self) -> dict:
        """
        Serialize the MinioConfig to a dictionary.

        :return: A dictionary representation of the MinioConfig.
        """
        # Using self.__dict__ directly for dataclasses is generally fine,
        # but ensure all fields are serializable (e.g., no complex objects
        # that aren't handled by the JSON serializer later).
        return self.__dict__.copy() # Return a copy

    def envs(self) -> dict:
        """
        Return environment variables for functions to connect to this Minio instance.

        :return: Dictionary of Minio-related environment variables.
        """
        return {
            "MINIO_ADDRESS": f"{self.address}:{self.mapped_port}", # Include port in address
            "MINIO_ACCESS_KEY": self.access_key,
            "MINIO_SECRET_KEY": self.secret_key,
        }


@dataclass
class NoSQLStorageConfig(ABC):
    """
    Abstract base class for NoSQL storage configurations.

    Defines the interface for serializing the configuration.
    """
    @abstractmethod
    def serialize(self) -> dict:
        """
        Serialize the NoSQL storage configuration to a dictionary.

        :return: A dictionary representation of the configuration.
        """
        pass


@dataclass
class ScyllaDBConfig(NoSQLStorageConfig):
    """
    Configuration for a self-hosted ScyllaDB NoSQL database.

    Attributes:
        address: Network address of the ScyllaDB server.
        mapped_port: Host port mapped to the ScyllaDB container's CQL port.
        alternator_port: Host port mapped to ScyllaDB's Alternator (DynamoDB compatible) port.
        access_key: Access key (typically "None" for ScyllaDB unless auth is configured).
        secret_key: Secret key (typically "None" for ScyllaDB).
        instance_id: Docker container ID of the running ScyllaDB instance.
        region: Region (typically "None" for self-hosted ScyllaDB).
        cpus: Number of CPUs allocated to the ScyllaDB container.
        memory: Memory allocated to the ScyllaDB container (in MB or similar unit).
        version: Version of the ScyllaDB Docker image.
        data_volume: Name of the Docker volume used for ScyllaDB data persistence.
    """
    address: str = ""
    mapped_port: int = -1
    alternator_port: int = 8000 # Default ScyllaDB Alternator port in container
    access_key: str = "None"
    secret_key: str = "None"
    instance_id: str = ""
    region: str = "None" # ScyllaDB is self-hosted, region might not be applicable like in cloud
    cpus: int = -1
    memory: int = -1 # e.g. in MB
    version: str = ""
    data_volume: str = ""

    def update_cache(self, path: List[str], cache: Cache):
        """
        Update the SeBS cache with the ScyllaDB configuration details.

        Iterates over dataclass fields and updates them in the cache under the given path.

        :param path: List of keys defining the path in the cache structure.
        :param cache: The Cache client instance.
        """
        for key_name in self.__dataclass_fields__.keys():
            cache.update_config(val=getattr(self, key_name), keys=[*path, key_name])

    @staticmethod
    def deserialize(data: dict) -> "ScyllaDBConfig":
        """
        Deserialize a ScyllaDBConfig object from a dictionary.

        Filters the input dictionary to include only known fields of ScyllaDBConfig.

        :param data: Dictionary containing ScyllaDBConfig data.
        :return: A ScyllaDBConfig instance.
        """
        known_keys = list(ScyllaDBConfig.__dataclass_fields__.keys())
        filtered_data = {k: v for k, v in data.items() if k in known_keys}
        return ScyllaDBConfig(**filtered_data)

    def serialize(self) -> dict:
        """
        Serialize the ScyllaDBConfig to a dictionary.

        :return: A dictionary representation of the ScyllaDBConfig.
        """
        return self.__dict__.copy() # Return a copy
