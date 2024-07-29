from dataclasses import dataclass
from typing import cast, Dict, List, Optional, Tuple

from sebs.azure.cli import AzureCLI
from sebs.azure.resources import CosmosDBAccount
from sebs.cache import Cache
from sebs.azure.config import AzureResources
from sebs.faas.nosql import NoSQLStorage

from azure.cosmos import CosmosClient, DatabaseProxy, PartitionKey
from azure.cosmos.exceptions import CosmosResourceNotFoundError


@dataclass
class BenchmarkResources:

    database: str
    containers: List[str]
    # We allocate this dynamically - ignore when caching
    database_client: Optional[DatabaseProxy] = None

    def serialize(self) -> dict:
        return {"database": self.database, "containers": self.containers}

    @staticmethod
    def deserialize(config: dict) -> "BenchmarkResources":
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

    def retrieve_cache(self, benchmark: str) -> bool:

        if benchmark in self._benchmark_resources:
            return True

        cached_storage = self.cache_client.get_nosql_config(self.deployment_name(), benchmark)
        if cached_storage is not None:
            self._benchmark_resources[benchmark] = BenchmarkResources.deserialize(cached_storage)
            return True

        return False

    def update_cache(self, benchmark: str):

        self._cache_client.update_nosql(
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
        assert self._cosmosdb_account is not None
        return (
            self._cosmosdb_account.account_name,
            self._cosmosdb_account.url,
            self._cosmosdb_account.credential,
        )

    def create_table(
        self, benchmark: str, name: str, primary_key: str, _: Optional[str] = None
    ) -> str:

        benchmark_resources = self._benchmark_resources.get(benchmark, None)

        if benchmark_resources is not None and name in benchmark_resources.containers:
            self.logging.info(f"Using existing CosmosDB container {name}")

        # Each benchmark receives its own CosmosDB database
        if benchmark_resources is None:

            # Get or allocate database
            try:
                db_client = self.cosmos_client().get_database_client(benchmark)
            except CosmosResourceNotFoundError:
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
            benchmark_resources.database_client.get_container_client(name)

        except CosmosResourceNotFoundError:
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
