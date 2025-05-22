from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

from sebs.cache import Cache
from sebs.faas.config import Resources
from sebs.faas.nosql import NoSQLStorage
from sebs.gcp.cli import GCloudCLI

from google.cloud import datastore


@dataclass
class BenchmarkResources:
    """
    Dataclass to hold Google Cloud Datastore resources specific to a benchmark.

    Attributes:
        database: Name of the Datastore database (Firestore in Datastore mode).
        kinds: List of Datastore "kind" names (analogous to tables) used by the benchmark.
        database_client: Optional Datastore client instance (dynamically allocated, not cached).
    """
    database: str
    kinds: List[str]
    # We allocate this dynamically - ignore when caching
    database_client: Optional[datastore.Client] = None

    def serialize(self) -> dict:
        """
        Serialize BenchmarkResources to a dictionary for caching.
        Excludes the database_client.

        :return: Dictionary with 'database' and 'kinds'.
        """
        return {"database": self.database, "kinds": self.kinds}

    @staticmethod
    def deserialize(config: dict) -> "BenchmarkResources":
        """
        Deserialize BenchmarkResources from a dictionary (typically from cache).

        :param config: Dictionary with 'database' and 'kinds'.
        :return: BenchmarkResources instance.
        """
        return BenchmarkResources(database=config["database"], kinds=config["kinds"])


class Datastore(NoSQLStorage):
    """Google Cloud Datastore (Firestore in Datastore mode) NoSQL storage implementation."""
    @staticmethod
    def typename() -> str:
        """Return the type name of the NoSQL storage implementation."""
        return "GCP.Datastore"

    @staticmethod
    def deployment_name():
        """Return the deployment name for GCP (gcp)."""
        return "gcp"

    def __init__(
        self, cli_instance: GCloudCLI, cache_client: Cache, resources: Resources, region: str
    ):
        """
        Initialize Datastore client and internal resource tracking.

        :param cli_instance: GCloudCLI instance.
        :param cache_client: Cache client instance.
        :param resources: GCPResources instance.
        :param region: GCP region.
        """
        super().__init__(region, cache_client, resources)
        self._cli_instance = cli_instance
        self._region = region

        # Mapping: benchmark -> Datastore database and kinds
        self._benchmark_resources: Dict[str, BenchmarkResources] = {}

    def get_tables(self, benchmark: str) -> Dict[str, str]:
        """
        Get the mapping of benchmark-specific table names to actual Datastore kinds.
        GCP Datastore uses "kinds" which are directly named; no explicit mapping is stored here.
        Thus, an empty dictionary is returned as the names are directly used.

        :param benchmark: Name of the benchmark.
        :return: Empty dictionary.
        """
        return {}

    def _get_table_name(self, benchmark: str, table: str) -> Optional[str]:
        """
        Get the actual Datastore kind name for a given benchmark and table alias.
        In Datastore's case, the table alias is the kind name if it's registered
        for the benchmark.

        :param benchmark: Name of the benchmark.
        :param table: Alias of the table (kind name) used within the benchmark.
        :return: Actual Datastore kind name, or None if not found for the benchmark.
        """
        if benchmark not in self._benchmark_resources:
            return None

        if table not in self._benchmark_resources[benchmark].kinds:
            return None

        return table

    def retrieve_cache(self, benchmark: str) -> bool:
        """
        Retrieve benchmark-specific Datastore resource details (database, kinds) from cache.

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
        Update the cache with the current benchmark-specific Datastore resource details.

        :param benchmark: Name of the benchmark.
        """
        self._cache_client.update_nosql(
            self.deployment_name(), benchmark, self._benchmark_resources[benchmark].serialize()
        )

    def benchmark_database(self, benchmark: str) -> str:
        """
        Get the name of the Datastore database used for a specific benchmark.

        :param benchmark: Name of the benchmark.
        :return: Name of the Datastore database.
        """
        return self._benchmark_resources[benchmark].database

    def write_to_table(
        self,
        benchmark: str,
        table: str,
        data: dict,
        primary_key: Tuple[str, str],
        secondary_key: Optional[Tuple[str, str]] = None,
    ):
        """
        Write data to a Google Cloud Datastore kind (table).

        Uses the secondary key as the entity's key name/ID and the primary key
        as part of the parent key for organizational purposes if provided.
        The actual partitioning/sharding is handled by Datastore based on the key structure.

        :param benchmark: Name of the benchmark.
        :param table: Name of the Datastore kind.
        :param data: Dictionary containing the data to write.
        :param primary_key: Tuple of (ancestor_kind, ancestor_id) for the parent key.
                            Datastore uses this for entity groups, not strict partitioning like DynamoDB.
        :param secondary_key: Tuple (kind_for_id, id_value) where id_value is used as the entity's ID/name.
                              The kind_for_id is used for the parent key.
        :raises AssertionError: If secondary_key is None, as it's used for the entity ID.
        """
        res = self._benchmark_resources[benchmark]
        kind_name = self._get_table_name(benchmark, table) # 'table' is the kind name
        assert kind_name is not None, f"Kind {table} not registered for benchmark {benchmark}"

        # In Datastore, the entity's own key can have an ID (name or integer).
        # The secondary_key's value is used as this ID.
        # The primary_key (if representing an ancestor) helps group entities.
        assert secondary_key is not None, "Datastore entity requires an ID/name from secondary_key."
        entity_id = secondary_key[1]

        if res.database_client is None:
            res.database_client = datastore.Client(database=res.database)

        # Construct the entity key.
        # If primary_key is (ancestor_kind, ancestor_id), it forms the parent.
        parent_key = None
        if primary_key and primary_key[0] and primary_key[1]:
             # Assuming primary_key[0] is ancestor kind, primary_key[1] is ancestor id/name
            parent_key = res.database_client.key(primary_key[0], primary_key[1])

        entity_key = res.database_client.key(kind_name, entity_id, parent=parent_key)

        entity = datastore.Entity(key=entity_key)
        entity.update(data)
        res.database_client.put(entity)

    def create_table(
        self, benchmark: str, name: str, primary_key: str, _: Optional[str] = None
    ) -> str:
        """
        Ensure a Datastore "kind" (analogous to a table) is noted for a benchmark
        and that its associated database (Firestore in Datastore mode) exists.

        If the database for the benchmark doesn't exist, it's created using gcloud CLI.
        Datastore kinds are schemaless and created implicitly when an entity of that
        kind is first written. This method primarily ensures the database exists and
        registers the kind name for the benchmark. The `primary_key` is noted but
        not directly used to create schema for the kind itself, as Datastore is schemaless.
        The secondary_key parameter is ignored.

        :param benchmark: Name of the benchmark.
        :param name: Name of the Datastore kind to register/use.
        :param primary_key: Name of the attribute often used as a primary/partition key conceptually.
        :param _: Secondary key (ignored for Datastore kind creation).
        :return: The name of the kind (which is `name`).
        :raises RuntimeError: If database creation or query fails.
        """
        benchmark_resources = self._benchmark_resources.get(benchmark, None)

        if benchmark_resources is not None and name in benchmark_resources.kinds:
            self.logging.info(f"Using cached Datastore kind {name}")
            # Ensure database_client is initialized if loaded from cache
            if benchmark_resources.database_client is None:
                benchmark_resources.database_client = datastore.Client(database=benchmark_resources.database)
            return name

        # If no resources registered for this benchmark, means we need to ensure/create the database
        if benchmark_resources is None:
            database_name = f"sebs-benchmarks-{self._cloud_resources.resources_id}-{benchmark}"
            try:
                # Check if database exists
                self._cli_instance.execute(
                    f"gcloud firestore databases describe --database='{database_name}' --format='json'"
                )
                self.logging.info(f"Using existing Firestore database {database_name} in Datastore mode.")
            except RuntimeError as e:
                if "NOT_FOUND" in str(e):
                    # Allocate a new Firestore database in Datastore mode
                    self.logging.info(f"Allocating a new Firestore database {database_name} in Datastore mode.")
                    self._cli_instance.execute(
                        f"gcloud firestore databases create --database='{database_name}' "
                        f"--location={self.region} --type='datastore-mode'"
                    )
                    self.logging.info(f"Allocated a new Firestore database {database_name}")
                else:
                    self.logging.error(f"Couldn't query Datastore database {database_name}: {e}")
                    raise RuntimeError(f"Couldn't query Datastore database {database_name}!")

            db_client = datastore.Client(database=database_name)
            benchmark_resources = BenchmarkResources(
                database=database_name, kinds=[], database_client=db_client
            )
            self._benchmark_resources[benchmark] = benchmark_resources
        elif benchmark_resources.database_client is None: # Ensure client if benchmark_resources existed but client was not set
            benchmark_resources.database_client = datastore.Client(database=benchmark_resources.database)


        # Add kind to the list for this benchmark if not already present
        if name not in benchmark_resources.kinds:
            benchmark_resources.kinds.append(name)
            self.logging.info(f"Registered kind {name} for benchmark {benchmark} in database {benchmark_resources.database}")

        return name

    def clear_table(self, name: str) -> str:
        """
        Clear all entities from a Datastore kind.

        Note: This method is not implemented. Deleting all entities from a kind
        efficiently requires careful implementation, often involving batched deletes
        or specific Datastore APIs.

        :param name: Name of the kind to clear.
        :raises NotImplementedError: This method is not yet implemented.
        """
        raise NotImplementedError()

    def remove_table(self, name: str) -> str:
        """
        Remove a Datastore kind (conceptually, as kinds are schemaless).

        Note: This method is not implemented. Removing a "kind" in Datastore
        means deleting all entities of that kind. There isn't a direct "drop kind"
        operation like "drop table".

        :param name: Name of the kind to remove/clear.
        :raises NotImplementedError: This method is not yet implemented.
        """
        raise NotImplementedError()
