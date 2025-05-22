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
    """
    Dataclass to hold Azure CosmosDB resources specific to a benchmark.

    Attributes:
        database: Name of the CosmosDB database.
        containers: List of container names within the database.
        database_client: Optional CosmosDB DatabaseProxy instance (dynamically allocated, not cached).
    """
    database: str
    containers: List[str]
    # We allocate this dynamically - ignore when caching
    database_client: Optional[DatabaseProxy] = None

    def serialize(self) -> dict:
        """
        Serialize BenchmarkResources to a dictionary for caching.
        Excludes the database_client.

        :return: Dictionary with 'database' and 'containers'.
        """
        return {"database": self.database, "containers": self.containers}

    @staticmethod
    def deserialize(config: dict) -> "BenchmarkResources":
        """
        Deserialize BenchmarkResources from a dictionary (typically from cache).

        :param config: Dictionary with 'database' and 'containers'.
        :return: BenchmarkResources instance.
        """
        return BenchmarkResources(database=config["database"], containers=config["containers"])


class CosmosDB(NoSQLStorage):
    """Azure CosmosDB NoSQL storage implementation."""
    @staticmethod
    def typename() -> str:
        """Return the type name of the NoSQL storage implementation."""
        return "Azure.CosmosDB"

    @staticmethod
    def deployment_name():
        """Return the deployment name for Azure (azure)."""
        return "azure"

    def __init__(self, cli: AzureCLI, cache_client: Cache, resources: AzureResources, region: str):
        """
        Initialize CosmosDB client and internal resource tracking.

        :param cli: AzureCLI instance.
        :param cache_client: Cache client instance.
        :param resources: AzureResources instance.
        :param region: Azure region.
        """
        super().__init__(region, cache_client, resources)
        self._cli_instance = cli
        self._resource_group = resources.resource_group(self._cli_instance)

        self._benchmark_resources: Dict[str, BenchmarkResources] = {}
        self._cosmos_client: Optional[CosmosClient] = None
        self._cosmosdb_account: Optional[CosmosDBAccount] = None

    def get_tables(self, benchmark: str) -> Dict[str, str]:
        """
        Get the mapping of benchmark-specific table names to actual Azure CosmosDB container names.
        Azure requires no table mappings: the name of container is the same as benchmark name.
        Thus, an empty dictionary is returned as the names are directly used.

        :param benchmark: Name of the benchmark.
        :return: Empty dictionary.
        """
        return {}

    def _get_table_name(self, benchmark: str, table: str) -> Optional[str]:
        """
        Get the actual Azure CosmosDB container name for a given benchmark and table alias.
        In CosmosDB's case, the table alias is the container name if it's registered.

        :param benchmark: Name of the benchmark.
        :param table: Alias of the table (container name) used within the benchmark.
        :return: Actual Azure CosmosDB container name, or None if not found for the benchmark.
        """
        if benchmark not in self._benchmark_resources:
            return None

        if table not in self._benchmark_resources[benchmark].containers:
            return None

        return table

    def retrieve_cache(self, benchmark: str) -> bool:
        """
        Retrieve benchmark-specific CosmosDB resource details (database, containers) from cache.

        Populates `_benchmark_resources` if cached data is found.

        :param benchmark: Name of the benchmark.
        :return: True if cache was retrieved, False otherwise.
        """
        if benchmark in self._benchmark_resources:
            return True

        cached_storage = self.cache_client.get_nosql_config(self.deployment_name(), benchmark)
        if cached_storage is not None:
            self._benchmark_resources[benchmark] = BenchmarkResources.deserialize(cached_storage)
            return True

        return False

    def update_cache(self, benchmark: str):
        """
        Update the cache with the current benchmark-specific CosmosDB resource details.

        :param benchmark: Name of the benchmark.
        """
        self.cache_client.update_nosql(
            self.deployment_name(), benchmark, self._benchmark_resources[benchmark].serialize()
        )

    def cosmos_client(self) -> CosmosClient:
        """
        Get or initialize the Azure CosmosDB client.

        Retrieves CosmosDB account details (URL, credentials) if not already available.

        :return: CosmosClient instance.
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
        """
        Check if CosmosDB resources (database, containers) are registered for a benchmark.

        :param benchmark: Name of the benchmark.
        :return: True if resources are registered, False otherwise.
        """
        return benchmark in self._benchmark_resources

    def benchmark_database(self, benchmark: str) -> str:
        """
        Get the name of the CosmosDB database used for a specific benchmark.

        :param benchmark: Name of the benchmark.
        :return: Name of the CosmosDB database.
        """
        return self._benchmark_resources[benchmark].database

    def credentials(self) -> Tuple[str, str, str]:
        """
        Get the credentials for the CosmosDB account.

        Retrieves account name, URL, and primary key. Initializes the
        CosmosDB account details if not already done.

        :return: Tuple containing (account_name, url, credential_key).
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
    ):
        """
        Write data to an Azure CosmosDB container.

        The secondary key, if provided, is expected to be named 'id' in CosmosDB.

        :param benchmark: Name of the benchmark.
        :param table: Name of the container.
        :param data: Dictionary containing the data to write.
        :param primary_key: Tuple of (partition_key_name, partition_key_value).
        :param secondary_key: Optional tuple for the item ID (item_id_name, item_id_value).
                              The item_id_name is ignored, 'id' is used.
        """
        res = self._benchmark_resources[benchmark]
        table_name = self._get_table_name(benchmark, table)
        assert table_name is not None

        data[primary_key[0]] = primary_key[1]
        # secondary key must have that name in CosmosDB
        # FIXME: support both options for naming the ID key
        assert secondary_key is not None, "CosmosDB requires an 'id' field (secondary_key)."
        data["id"] = secondary_key[1]

        if res.database_client is None:
            res.database_client = self.cosmos_client().get_database_client(benchmark)

        container_client = res.database_client.get_container_client(table_name)
        container_client.create_item(data)

    def create_table(
        self, benchmark: str, name: str, primary_key: str, _: Optional[str] = None
    ) -> str:
        """
        Create an Azure CosmosDB container within a benchmark-specific database.

        If the database for the benchmark doesn't exist, it's created.
        If the container doesn't exist, it's created with the specified primary key
        as the partition key. The secondary key parameter is ignored for CosmosDB schema.

        For some reason, creating the client is enough to verify existence of db/container.
        We need to force the client to make some actions; that's why we call read.

        :param benchmark: Name of the benchmark.
        :param name: Name of the container to create.
        :param primary_key: Name of the attribute to use as the partition key.
        :param _: Secondary key (ignored for CosmosDB container creation).
        :return: Name of the created or existing container.
        """
        benchmark_resources = self._benchmark_resources.get(benchmark, None)

        if benchmark_resources is not None and name in benchmark_resources.containers:
            self.logging.info(f"Using cached CosmosDB container {name}")
            # Ensure database_client is initialized if loaded from cache
            if benchmark_resources.database_client is None:
                 benchmark_resources.database_client = self.cosmos_client().get_database_client(benchmark)
            return name

        # Each benchmark receives its own CosmosDB database
        if benchmark_resources is None:
            # Get or allocate database
            try:
                db_client = self.cosmos_client().get_database_client(benchmark)
                db_client.read() # Force action to check existence
                self.logging.info(f"Using existing CosmosDB database {benchmark}")
            except CosmosResourceNotFoundError:
                self.logging.info(f"Creating CosmosDB database {benchmark}")
                db_client = self.cosmos_client().create_database(benchmark)

            benchmark_resources = BenchmarkResources(
                database=benchmark, database_client=db_client, containers=[]
            )
            self._benchmark_resources[benchmark] = benchmark_resources
        elif benchmark_resources.database_client is None:
            # Data loaded from cache will miss database client
            benchmark_resources.database_client = self.cosmos_client().get_database_client(
                benchmark
            )

        try:
            # verify container exists by trying to read it
            benchmark_resources.database_client.get_container_client(name).read()
            self.logging.info(f"Using existing CosmosDB container {name}")
        except CosmosResourceNotFoundError:
            self.logging.info(f"Creating CosmosDB container {name}")
            # no container with such name -> allocate
            benchmark_resources.database_client.create_container(
                id=name, partition_key=PartitionKey(path=f"/{primary_key}")
            )

        if name not in benchmark_resources.containers:
            benchmark_resources.containers.append(name)

        return name

    def clear_table(self, name: str) -> str:
        """
        Clear all items from a CosmosDB container.

        Note: This method is not implemented.

        :param name: Name of the container to clear.
        :raises NotImplementedError: This method is not yet implemented.
        """
        raise NotImplementedError()

    def remove_table(self, name: str) -> str:
        """
        Remove a CosmosDB container.

        Note: This method is not implemented.

        :param name: Name of the container to remove.
        :raises NotImplementedError: This method is not yet implemented.
        """
        raise NotImplementedError()
