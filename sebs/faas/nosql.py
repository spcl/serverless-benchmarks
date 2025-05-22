from abc import ABC
from abc import abstractmethod
from typing import Dict, Optional, Tuple

from sebs.faas.config import Resources
from sebs.cache import Cache
from sebs.utils import LoggingBase


class NoSQLStorage(ABC, LoggingBase):
    """
    Abstract base class for NoSQL storage services used by benchmarks.

    Provides an interface for creating, managing, and interacting with
    NoSQL tables/containers across different FaaS providers.
    """
    @staticmethod
    @abstractmethod
    def deployment_name() -> str:
        """
        Return the name of the FaaS deployment this NoSQL storage belongs to
        (e.g., "aws", "azure").

        :return: Deployment name string.
        """
        pass

    @property
    def cache_client(self) -> Cache:
        """The cache client instance for storing/retrieving NoSQL configurations."""
        return self._cache_client

    @property
    def region(self) -> str: # Added return type
        """The cloud region where the NoSQL storage is located."""
        return self._region

    def __init__(self, region: str, cache_client: Cache, resources: Resources):
        """
        Initialize the NoSQLStorage instance.

        :param region: The cloud region.
        :param cache_client: The cache client instance.
        :param resources: The cloud resources configuration object.
        """
        super().__init__()
        self._cache_client = cache_client
        self._cached = False # Indicates if current benchmark's table info is from cache
        self._region = region
        self._cloud_resources = resources

    @abstractmethod
    def get_tables(self, benchmark: str) -> Dict[str, str]:
        """
        Get a mapping of benchmark-defined table names to actual cloud provider table names.

        For some providers, this might be an empty dictionary if names are directly used.

        :param benchmark: The name of the benchmark.
        :return: Dictionary mapping logical table names to actual table names.
        """
        pass

    @abstractmethod
    def _get_table_name(self, benchmark: str, table: str) -> Optional[str]:
        """
        Get the actual cloud provider table name for a given benchmark and logical table name.

        :param benchmark: The name of the benchmark.
        :param table: The logical name of the table within the benchmark.
        :return: The actual table name in the cloud, or None if not found.
        """
        pass

    @abstractmethod
    def retrieve_cache(self, benchmark: str) -> bool:
        """
        Retrieve NoSQL table configurations for a benchmark from the cache.

        Implementations should populate internal structures with cached table names/details.

        :param benchmark: The name of the benchmark.
        :return: True if cached data was successfully retrieved, False otherwise.
        """
        pass

    @abstractmethod
    def update_cache(self, benchmark: str):
        """
        Update the cache with the current NoSQL table configurations for a benchmark.

        :param benchmark: The name of the benchmark.
        """
        pass

    def envs(self) -> dict:
        """
        Return a dictionary of environment variables that might be needed by functions
        to access this NoSQL storage (e.g., connection strings, table names).

        Default implementation returns an empty dictionary. Subclasses should override
        if they need to expose environment variables.

        :return: Dictionary of environment variables.
        """
        return {}

    def create_benchmark_tables(
        self, benchmark: str, name: str, primary_key: str, secondary_key: Optional[str] = None
    ):
        """
        Ensure that a NoSQL table/container required by a benchmark exists.

        Table names typically follow the pattern:
        `sebs-benchmarks-{resource_id}-{benchmark-name}-{table-name}`

        Workflow:
        1. Attempt to retrieve table information from cache.
        2. If cached and table exists, do nothing further for that specific table.
        3. If not cached or table doesn't exist, proceed to create it using `create_table`.
        4. Cache update is handled separately after data upload by the benchmark.

        :param benchmark: The name of the benchmark.
        :param name: The logical name of the table within the benchmark.
        :param primary_key: The name of the primary/partition key for the table.
        :param secondary_key: Optional name of the secondary/sort key.
        """
        if self.retrieve_cache(benchmark):
            table_name = self._get_table_name(benchmark, name)
            if table_name is not None:
                self.logging.info(
                    f"Using cached NoSQL table {table_name} for benchmark {benchmark}"
                )
                return

        self.logging.info(f"Preparing to create a NoSQL table {name} for benchmark {benchmark}")
        self.create_table(benchmark, name, primary_key, secondary_key)

    @abstractmethod
    def create_table(
        self, benchmark: str, name: str, primary_key: str, secondary_key: Optional[str] = None
    ) -> str:
        """
        Create a NoSQL table/container.

        Provider-specific implementation details:
        - AWS: DynamoDB Table
        - Azure: CosmosDB Container
        - Google Cloud: Firestore in Datastore Mode, Database/Collection

        :param benchmark: The name of the benchmark.
        :param name: The logical name of the table/container.
        :param primary_key: The name of the primary/partition key.
        :param secondary_key: Optional name of the secondary/sort key.
        :return: The actual name of the created table/container in the cloud.
        """
        pass

    @abstractmethod
    def write_to_table(
        self,
        benchmark: str,
        table: str,
        data: dict,
        primary_key: Tuple[str, str],
        secondary_key: Optional[Tuple[str, str]] = None,
    ):
        """
        Write an item/document to the specified table/container.

        :param benchmark: The name of the benchmark.
        :param table: The logical name of the table/container.
        :param data: The data to write (as a dictionary).
        :param primary_key: A tuple (key_name, key_value) for the primary/partition key.
        :param secondary_key: Optional tuple for the secondary/sort key or item ID.
        """
        pass

    @abstractmethod
    def clear_table(self, name: str) -> str:
        """
        Clear all items from a table/container.

        Provider-specific implementation details:
        - AWS DynamoDB: Removing & recreating table is often the cheapest & fastest option.
        - Azure CosmosDB: Recreate container or use specific API to delete items.
        - Google Cloud: Likely recreate collection or use specific API.

        :param name: The actual name of the table/container in the cloud.
        :return: Status or confirmation message.
        """
        pass

    @abstractmethod
    def remove_table(self, name: str) -> str:
        """
        Remove/delete a table/container completely.

        :param name: The actual name of the table/container in the cloud.
        :return: Status or confirmation message.
        """
        pass
