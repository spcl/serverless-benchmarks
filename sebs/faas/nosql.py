from abc import ABC
from abc import abstractmethod
from collections import defaultdict
from typing import Dict

from sebs.faas.config import Resources
from sebs.cache import Cache
from sebs.utils import LoggingBase


class NoSQLStorage(ABC, LoggingBase):
    @staticmethod
    @abstractmethod
    def deployment_name() -> str:
        pass

    @property
    def cache_client(self) -> Cache:
        return self._cache_client

    @property
    def region(self):
        return self._region

    def __init__(self, region: str, cache_client: Cache, resources: Resources):
        super().__init__()
        self._cache_client = cache_client
        self._cached = False
        self._region = region
        self._cloud_resources = resources

        # Map benchmark -> orig_name -> table_name
        self._tables: Dict[str, Dict[str, str]] = defaultdict(dict)

    def get_tables(self, benchmark: str) -> Dict[str, str]:
        return self._tables[benchmark]

    def retrieve_cache(self, benchmark: str) -> bool:

        if benchmark in self._tables:
            return True

        cached_storage = self.cache_client.get_nosql_config(self.deployment_name(), benchmark)
        if cached_storage is not None:
            print(cached_storage["tables"])
            self._tables[benchmark] = cached_storage["tables"]
            return True

        return False

    def update_cache(self, benchmark: str):

        self._cache_client.update_nosql(
            self.deployment_name(),
            benchmark,
            {
                "tables": self._tables[benchmark],
            },
        )

    """
        Each table name follow this pattern:
        sebs-benchmarks-{resource_id}-{benchmark-name}-{table-name}

        Each implementation should do the following
        (1) Retrieve cached data
        (2) Create missing table that do not exist
        (3) Update cached data if anything new was created
    """

    def create_benchmark_tables(self, benchmark: str, name: str, primary_key: str):

        table_name = f"sebs-benchmarks-{self._cloud_resources.resources_id}-{benchmark}-{name}"

        self.logging.info(
            f"Preparing to create a NoSQL table {table_name} for benchmark {benchmark}"
        )

        if self.retrieve_cache(benchmark):

            if table_name in self._tables[benchmark]:
                self.logging.info("Table {table_name} already exists in cache")
                return

        self.create_table(benchmark, table_name, primary_key)
        print(type(self._tables))
        print(self._tables[benchmark])
        self._tables[benchmark][name] = table_name

        self.update_cache(benchmark)

    """

        AWS: DynamoDB Table
        Azure: CosmosDB Container
        Google Cloud: Firestore in Datastore Mode, Database
    """

    @abstractmethod
    def create_table(self, benchmark: str, name: str, primary_key: str) -> str:
        pass

    """

        AWS DynamoDB: Removing & recreating table is the cheapest & fastest option

        Azure CosmosDB: recreate container

        Google Cloud: also likely recreate

    """

    @abstractmethod
    def clear_table(self, name: str) -> str:
        pass

    @abstractmethod
    def remove_table(self, name: str) -> str:
        pass
