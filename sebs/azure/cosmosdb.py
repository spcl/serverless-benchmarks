"""Azure CosmosDB integration for SeBS NoSQL benchmarking.

This module provides Azure CosmosDB integration for NoSQL benchmarks in the
SeBS benchmarking suite. It handles database and container management,
data operations, and resource lifecycle for NoSQL-based benchmarks.

The module includes:
    - BenchmarkResources: Dataclass for managing benchmark-specific resources
    - CosmosDB: Main class for CosmosDB operations and management

Example:
    Basic usage for CosmosDB operations:
    
    ```python
    from sebs.azure.cosmosdb import CosmosDB
    
    # Initialize CosmosDB with account
    cosmosdb = CosmosDB(cache, resources, cosmosdb_account)
    
    # Set up benchmark database and containers
    db_name = cosmosdb.benchmark_database("my-benchmark")
    tables = cosmosdb.get_tables("my-benchmark")
    
    # Perform operations
    credentials = cosmosdb.credentials()
    ```
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
    @staticmethod
    def typename() -> str:
        return "Azure.CosmosDB"

    @staticmethod
    def deployment_name():
        return "azure"

    def __init__(self, cli: AzureCLI, cache_client: Cache, resources: AzureResources, region: str):
        super().__init__(region, cache_client, resources)
        self._cli_instance = cli
        self._resource_group = resources.resource_group(self._cli_instance)

        self._benchmark_resources: Dict[str, BenchmarkResources] = {}
        self._cosmos_client: Optional[CosmosClient] = None
        self._cosmosdb_account: Optional[CosmosDBAccount] = None

    """
        Azure requires no table mappings: the name of container is the same as benchmark name.
    """

    def get_tables(self, benchmark: str) -> Dict[str, str]:
        return {}

    def _get_table_name(self, benchmark: str, table: str) -> Optional[str]:

        if benchmark not in self._benchmark_resources:
            return None

        if table not in self._benchmark_resources[benchmark].containers:
            return None

        return table

    def retrieve_cache(self, benchmark: str) -> bool:

        if benchmark in self._benchmark_resources:
            return True

        cached_storage = self.cache_client.get_nosql_config(self.deployment_name(), benchmark)
        if cached_storage is not None:
            self._benchmark_resources[benchmark] = BenchmarkResources.deserialize(cached_storage)
            return True

        return False

    def update_cache(self, benchmark: str):

        self.cache_client.update_nosql(
            self.deployment_name(), benchmark, self._benchmark_resources[benchmark].serialize()
        )

    def cosmos_client(self) -> CosmosClient:

        if self._cosmos_client is None:

            self._cosmosdb_account = cast(AzureResources, self._cloud_resources).cosmosdb_account(
                self._cli_instance
            )

            self._cosmos_client = CosmosClient(
                url=self._cosmosdb_account.url, credential=self._cosmosdb_account.credential
            )

        return self._cosmos_client

    def has_tables(self, benchmark: str) -> bool:
        return benchmark in self._benchmark_resources

    def benchmark_database(self, benchmark: str) -> str:
        return self._benchmark_resources[benchmark].database

    def credentials(self) -> Tuple[str, str, str]:

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

        benchmark_resources = self._benchmark_resources.get(benchmark, None)

        if benchmark_resources is not None and name in benchmark_resources.containers:
            self.logging.info(f"Using cached CosmosDB container {name}")

        """
            For some reason, creating the client is enough to verify existence of db/container.
            We need to force the client to make some actions; that's why we call read.
        """
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
        raise NotImplementedError()

    def remove_table(self, name: str) -> str:
        raise NotImplementedError()
