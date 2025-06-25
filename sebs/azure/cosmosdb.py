"""Azure CosmosDB integration for SeBS NoSQL benchmarking.

This module provides Azure CosmosDB integration for NoSQL benchmarks in the
SeBS benchmarking suite. It handles database and container management,
data operations, and resource lifecycle for NoSQL-based benchmarks.

The module includes:
    - BenchmarkResources: Dataclass for managing benchmark-specific resources
    - CosmosDB: Main class for CosmosDB operations and management

Example:
    Basic usage for CosmosDB operations:

    ::

        from sebs.azure.cosmosdb import CosmosDB

        # Initialize CosmosDB with account
        cosmosdb = CosmosDB(cache, resources, cosmosdb_account)

        # Set up benchmark database and containers
        db_name = cosmosdb.benchmark_database("my-benchmark")
        tables = cosmosdb.get_tables("my-benchmark")

        # Perform operations
        credentials = cosmosdb.credentials()
"""

from dataclasses import dataclass
from typing import cast, Dict, List, Optional, Tuple

from sebs.azure.cli import AzureCLI
from sebs.azure.cloud_resources import CosmosDBAccount
from sebs.cache import Cache
from sebs.azure.config import AzureResources
from sebs.faas.nosql import NoSQLStorage

from azure.cosmos import CosmosClient, DatabaseProxy, PartitionKey
from azure.cosmos.exceptions import CosmosResourceNotFoundError


@dataclass
class BenchmarkResources:
    """Resource container for benchmark-specific CosmosDB resources.

    This dataclass holds the database and container names allocated
    for a specific benchmark, along with the database client proxy.

    Attributes:
        database: Name of the CosmosDB database
        containers: List of container names for the benchmark
        database_client: CosmosDB database proxy (allocated dynamically)
    """

    database: str
    containers: List[str]
    # We allocate this dynamically - ignore when caching
    database_client: Optional[DatabaseProxy] = None

    def serialize(self) -> dict:
        """Serialize benchmark resources to dictionary.

        Returns:
            Dictionary containing database and container names.
        """
        return {"database": self.database, "containers": self.containers}

    @staticmethod
    def deserialize(config: dict) -> "BenchmarkResources":
        """Deserialize benchmark resources from dictionary.

        Args:
            config: Dictionary containing resource configuration

        Returns:
            BenchmarkResources instance with restored configuration.
        """
        return BenchmarkResources(database=config["database"], containers=config["containers"])


class CosmosDB(NoSQLStorage):
    """Azure CosmosDB implementation for NoSQL storage in SeBS benchmarking.

    This class provides Azure CosmosDB integration for NoSQL benchmarks,
    handling database and container management, data operations, and
    resource lifecycle. It supports benchmark-specific database allocation
    and container creation with proper caching and error handling.

    Azure CosmosDB uses a different model than traditional NoSQL databases:
    - Each benchmark gets its own database
    - Container names match benchmark table names directly
    - No table mappings are required
    - Partition keys are configured per container

    Attributes:
        _cli_instance: Azure CLI instance for CosmosDB operations
        _resource_group: Name of Azure resource group containing CosmosDB
        _benchmark_resources: Dict mapping benchmark names to their resources
        _cosmos_client: CosmosDB client for database operations
        _cosmosdb_account: CosmosDB account configuration and credentials
    """

    @staticmethod
    def typename() -> str:
        """Get the storage type name.

        Returns:
            String identifier for Azure CosmosDB storage type.
        """
        return "Azure.CosmosDB"

    @staticmethod
    def deployment_name() -> str:
        """Get the deployment platform name.

        Returns:
            String identifier for Azure deployment.
        """
        return "azure"

    def __init__(
        self, cli: AzureCLI, cache_client: Cache, resources: AzureResources, region: str
    ) -> None:
        """Initialize CosmosDB storage handler.

        Args:
            cli: Azure CLI instance for executing CosmosDB operations
            cache_client: Cache instance for storing/retrieving configurations
            resources: Azure resources manager for resource allocation
            region: Azure region for resource placement
        """
        super().__init__(region, cache_client, resources)
        self._cli_instance = cli
        self._resource_group = resources.resource_group(self._cli_instance)

        self._benchmark_resources: Dict[str, BenchmarkResources] = {}
        self._cosmos_client: Optional[CosmosClient] = None
        self._cosmosdb_account: Optional[CosmosDBAccount] = None

    def get_tables(self, benchmark: str) -> Dict[str, str]:
        """Get table mappings for benchmark.

        Azure requires no table mappings since container names match
        benchmark table names directly.

        Args:
            benchmark: Name of the benchmark

        Returns:
            Empty dictionary as no mappings are needed for Azure CosmosDB.
        """
        return {}

    def _get_table_name(self, benchmark: str, table: str) -> Optional[str]:
        """Get the actual table name for a benchmark table.

        Validates that the table exists in the benchmark's containers
        and returns the table name if found.

        Args:
            benchmark: Name of the benchmark
            table: Logical table name to resolve

        Returns:
            Actual table name if found, None if benchmark or table doesn't exist.
        """
        if benchmark not in self._benchmark_resources:
            return None

        if table not in self._benchmark_resources[benchmark].containers:
            return None

        return table

    def retrieve_cache(self, benchmark: str) -> bool:
        """Retrieve benchmark resources from cache.

        Attempts to load cached benchmark resources including database
        and container information from the filesystem cache.

        Args:
            benchmark: Name of the benchmark to retrieve from cache

        Returns:
            True if cache was found and loaded, False otherwise.
        """
        if benchmark in self._benchmark_resources:
            return True

        cached_storage = self.cache_client.get_nosql_config(self.deployment_name(), benchmark)
        if cached_storage is not None:
            self._benchmark_resources[benchmark] = BenchmarkResources.deserialize(cached_storage)
            return True

        return False

    def update_cache(self, benchmark: str) -> None:
        """Update benchmark resources in cache.

        Persists current benchmark resources including database and
        container information to the filesystem cache.

        Args:
            benchmark: Name of the benchmark to cache
        """
        self.cache_client.update_nosql(
            self.deployment_name(), benchmark, self._benchmark_resources[benchmark].serialize()
        )

    def cosmos_client(self) -> CosmosClient:
        """Get or create CosmosDB client.

        Initializes the CosmosDB client using the account credentials.
        The client is cached after first initialization.

        Returns:
            CosmosClient instance for database operations.
        """
        if self._cosmos_client is None:

            self._cosmosdb_account = cast(AzureResources, self._cloud_resources).cosmosdb_account(
                self._cli_instance
            )

            self._cosmos_client = CosmosClient(
                url=self._cosmosdb_account.url, credential=self._cosmosdb_account.credential
            )

        return self._cosmos_client

    def has_tables(self, benchmark: str) -> bool:
        """Check if benchmark has allocated tables.

        Args:
            benchmark: Name of the benchmark to check

        Returns:
            True if benchmark has allocated resources, False otherwise.
        """
        return benchmark in self._benchmark_resources

    def benchmark_database(self, benchmark: str) -> str:
        """Get database name for benchmark.

        Args:
            benchmark: Name of the benchmark

        Returns:
            Name of the CosmosDB database for the benchmark.

        Raises:
            KeyError: If benchmark resources are not allocated.
        """
        return self._benchmark_resources[benchmark].database

    def credentials(self) -> Tuple[str, str, str]:
        """Get CosmosDB account credentials.

        Retrieves the account name, URL, and credential for CosmosDB access.
        Initializes the CosmosDB account if not already done.

        Returns:
            Tuple containing (account_name, url, credential) for CosmosDB access.
        """
        # An update of function that uses fully cached data will have
        # to initialize it separately
        # There were no prior actions that initialized this variable
        if self._cosmosdb_account is None:
            self._cosmosdb_account = cast(AzureResources, self._cloud_resources).cosmosdb_account(
                self._cli_instance
            )

        return (
            self._cosmosdb_account.account_name,
            self._cosmosdb_account.url,
            self._cosmosdb_account.credential,
        )

    def write_to_table(
        self,
        benchmark: str,
        table: str,
        data: dict,
        primary_key: Tuple[str, str],
        secondary_key: Optional[Tuple[str, str]] = None,
    ) -> None:
        """Write data to CosmosDB container.

        Inserts data into the specified container with required key fields.
        CosmosDB requires both a partition key and an 'id' field for documents.

        Args:
            benchmark: Name of the benchmark
            table: Name of the container/table
            data: Dictionary data to insert
            primary_key: Tuple of (key_name, key_value) for partition key
            secondary_key: Tuple of (key_name, key_value) for document id

        Raises:
            AssertionError: If table name cannot be resolved or secondary_key is None.
        """
        res = self._benchmark_resources[benchmark]
        table_name = self._get_table_name(benchmark, table)
        assert table_name is not None

        data[primary_key[0]] = primary_key[1]
        # secondary key must have that name in CosmosDB
        # FIXME: support both options
        assert secondary_key is not None
        data["id"] = secondary_key[1]

        if res.database_client is None:
            res.database_client = self.cosmos_client().get_database_client(benchmark)

        container_client = res.database_client.get_container_client(table_name)
        container_client.create_item(data)

    def create_table(
        self, benchmark: str, name: str, primary_key: str, _: Optional[str] = None
    ) -> str:
        """Create CosmosDB container for benchmark table.

        Creates a new CosmosDB database and container for the benchmark if they
        don't exist. Each benchmark gets its own database, and containers are
        created within that database for each table.

        Args:
            benchmark: Name of the benchmark
            name: Name of the container/table to create
            primary_key: Partition key field name for the container
            _: Unused parameter for compatibility with base class

        Returns:
            Name of the created container.

        Raises:
            CosmosResourceNotFoundError: If database or container operations fail.
        """
        benchmark_resources = self._benchmark_resources.get(benchmark, None)

        if benchmark_resources is not None and name in benchmark_resources.containers:
            self.logging.info(f"Using cached CosmosDB container {name}")

        # For some reason, creating the client is enough to verify existence of db/container.
        # We need to force the client to make some actions; that's why we call read.

        # Each benchmark receives its own CosmosDB database
        if benchmark_resources is None:

            # Get or allocate database
            try:
                db_client = self.cosmos_client().get_database_client(benchmark)
                db_client.read()

            except CosmosResourceNotFoundError:
                self.logging.info(f"Creating CosmosDB database {benchmark}")
                db_client = self.cosmos_client().create_database(benchmark)

            benchmark_resources = BenchmarkResources(
                database=benchmark, database_client=db_client, containers=[]
            )
            self._benchmark_resources[benchmark] = benchmark_resources

        if benchmark_resources.database_client is None:
            # Data loaded from cache will miss database client
            benchmark_resources.database_client = self.cosmos_client().get_database_client(
                benchmark
            )

        try:
            # verify it exists
            benchmark_resources.database_client.get_container_client(name).read()
            self.logging.info(f"Using existing CosmosDB container {name}")

        except CosmosResourceNotFoundError:
            self.logging.info(f"Creating CosmosDB container {name}")
            # no container with such name -> allocate
            benchmark_resources.database_client.create_container(
                id=name, partition_key=PartitionKey(path=f"/{primary_key}")
            )

        benchmark_resources.containers.append(name)

        return name

    def clear_table(self, name: str) -> str:
        """Clear all data from a table.

        Args:
            name: Name of the table to clear

        Returns:
            Name of the cleared table.

        Raises:
            NotImplementedError: This operation is not yet implemented.
        """
        raise NotImplementedError()

    def remove_table(self, name: str) -> str:
        """Remove a table completely.

        Args:
            name: Name of the table to remove

        Returns:
            Name of the removed table.

        Raises:
            NotImplementedError: This operation is not yet implemented.
        """
        raise NotImplementedError()
