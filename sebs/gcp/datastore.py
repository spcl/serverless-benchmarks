"""Google Cloud Datastore/Firestore implementation for SeBS NoSQL storage.

This module provides NoSQL database functionality using Google Cloud Firestore
in Datastore mode. It manages database allocation, table creation, and data
operations for benchmarks requiring NoSQL storage capabilities.
To create databases, we use the gcloud CLI instance since there is no API
that we could access directly.

Classes:
    BenchmarkResources: Resource configuration for benchmark databases
    Datastore: NoSQL storage implementation using Google Cloud Firestore

Example:
    Using Datastore for benchmark NoSQL operations:

        datastore = Datastore(cli_instance, cache, resources, region)
        table_name = datastore.create_table("benchmark-name", "user-data", "user_id")
        datastore.write_to_table("benchmark-name", table_name, data, primary_key, secondary_key)
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

from sebs.cache import Cache
from sebs.faas.config import Resources
from sebs.faas.nosql import NoSQLStorage
from sebs.gcp.cli import GCloudCLI

from google.cloud import datastore


@dataclass
class BenchmarkResources:
    """Resource configuration for a benchmark's Datastore database.

    Tracks the allocated database name, table kinds, and client instance
    for a specific benchmark's NoSQL storage requirements.

    Attributes:
        database: Name of the Firestore database in Datastore mode
        kinds: List of entity kinds (table equivalents) in the database
        database_client: Optional Datastore client instance (allocated dynamically)
    """

    database: str
    kinds: List[str]
    # We allocate this dynamically - ignore when caching
    database_client: Optional[datastore.Client] = None

    def serialize(self) -> Dict:
        """Serialize benchmark resources for cache storage.

        Returns:
            Dictionary containing database name and kinds list
        """
        return {"database": self.database, "kinds": self.kinds}

    @staticmethod
    def deserialize(config: Dict) -> "BenchmarkResources":
        """Deserialize benchmark resources from cached configuration.

        Args:
            config: Dictionary containing cached resource configuration

        Returns:
            BenchmarkResources instance with database and kinds
        """
        return BenchmarkResources(database=config["database"], kinds=config["kinds"])


class Datastore(NoSQLStorage):
    """Google Cloud Firestore/Datastore implementation for NoSQL storage.

    Provides NoSQL database functionality using Google Cloud Firestore in
    Datastore mode. Manages database allocation, entity kind creation, and
    data operations for benchmarks requiring NoSQL capabilities.

    Attributes:
        _cli_instance: gcloud CLI interface for database management
        _region: GCP region for database allocation
        _benchmark_resources: Mapping of benchmarks to their database resources
    """

    @staticmethod
    def typename() -> str:
        """Get the type name for this NoSQL storage implementation.

        Returns:
            Type name string for GCP Datastore
        """
        return "GCP.Datastore"

    @staticmethod
    def deployment_name() -> str:
        """Get the deployment name for this NoSQL storage implementation.

        Returns:
            Deployment name string 'gcp'
        """
        return "gcp"

    def __init__(
        self, cli_instance: GCloudCLI, cache_client: Cache, resources: Resources, region: str
    ) -> None:
        """Initialize Datastore NoSQL storage manager.

        Args:
            cli_instance: gcloud CLI interface for database operations
            cache_client: Cache instance for storing resource state
            resources: Resource configuration
            region: GCP region for database allocation
        """
        super().__init__(region, cache_client, resources)
        self._cli_instance = cli_instance
        self._region = region

        # Mapping: benchmark -> Datastore database
        self._benchmark_resources: Dict[str, BenchmarkResources] = {}

    def get_tables(self, benchmark: str) -> Dict[str, str]:
        """Get table name mappings for a benchmark.

        GCP Datastore requires no table mappings as the entity kind name
        is the same as the benchmark table name.

        Args:
            benchmark: Name of the benchmark

        Returns:
            Empty dictionary (no mappings needed for GCP)
        """
        return {}

    def _get_table_name(self, benchmark: str, table: str) -> Optional[str]:
        """Get the actual table name for a benchmark table.

        In Datastore's case, the table alias is the kind name if it's registered
        for the benchmark.

        Args:
            benchmark: Name of the benchmark
            table: Logical table name

        Returns:
            Table name if it exists in benchmark resources, None otherwise
        """

        if benchmark not in self._benchmark_resources:
            return None

        if table not in self._benchmark_resources[benchmark].kinds:
            return None

        return table

    def retrieve_cache(self, benchmark: str) -> bool:
        """Retrieve benchmark resources from cache.

        Args:
            benchmark: Name of the benchmark to retrieve resources for

        Returns:
            True if resources were found in cache, False otherwise
        """

        if benchmark in self._benchmark_resources:
            return True

        cached_storage = self.cache_client.get_nosql_config(self.deployment_name(), benchmark)
        if cached_storage is not None:
            self._benchmark_resources[benchmark] = BenchmarkResources.deserialize(cached_storage)
            return True

        return False

    def update_cache(self, benchmark: str) -> None:
        """Update cache with current benchmark resources.

        Args:
            benchmark: Name of the benchmark to cache resources for
        """

        self._cache_client.update_nosql(
            self.deployment_name(), benchmark, self._benchmark_resources[benchmark].serialize()
        )

    def benchmark_database(self, benchmark: str) -> str:
        """Get the database name for a benchmark.

        Args:
            benchmark: Name of the benchmark

        Returns:
            Database name for the benchmark's NoSQL resources
        """
        return self._benchmark_resources[benchmark].database

    def write_to_table(
        self,
        benchmark: str,
        table: str,
        data: Dict,
        primary_key: Tuple[str, str],
        secondary_key: Optional[Tuple[str, str]] = None,
    ) -> None:
        """Write data to a Datastore entity kind (table).

        Args:
            benchmark: Name of the benchmark
            table: Name of the table (entity kind)
            data: Dictionary of data to write
            primary_key: Primary key tuple (name, value)
            secondary_key: Secondary key tuple (name, value) - required for GCP

        Raises:
            AssertionError: If secondary_key is None (required for GCP)
        """

        res = self._benchmark_resources[benchmark]
        table_name = self._get_table_name(benchmark, table)

        # FIXME: support both options
        assert secondary_key is not None

        if res.database_client is None:
            res.database_client = datastore.Client(database=res.database)

        parent_key = res.database_client.key(secondary_key[0], secondary_key[1])
        key = res.database_client.key(
            # kind determines the table
            table_name,
            # main ID key
            secondary_key[1],
            # organization key
            parent=parent_key,
        )

        val = datastore.Entity(key=key)
        val.update(data)
        res.database_client.put(val)

    def create_table(
        self, benchmark: str, name: str, primary_key: str, _: Optional[str] = None
    ) -> str:
        """Create a new entity kind (table) in Datastore.

        Creates a new Firestore database in Datastore mode if needed using gloud CLI.
        Datastore kinds are schemaless and created implicitly when an entity of that
        kind is first written. This method primarily ensures the database exists and
        registers the kind name for the benchmark. The `primary_key` is noted but
        not directly used to create schema for the kind itself, as Datastore is schemaless.

        Args:
            benchmark: Name of the benchmark
            name: Name of the entity kind (table) to create
            primary_key: Primary key field name
            _: Unused parameter for compatibility

        Returns:
            Name of the created entity kind

        Raises:
            RuntimeError: If database operations fail
        """

        benchmark_resources = self._benchmark_resources.get(benchmark, None)

        if benchmark_resources is not None and name in benchmark_resources.kinds:
            self.logging.info(f"Using cached Datastore kind {name}")
            return name

        """
            No data for this benchmark -> we need to allocate a new Datastore database.
        """

        if benchmark_resources is None:

            database_name = f"sebs-benchmarks-{self._cloud_resources.resources_id}-{benchmark}"

            try:

                self._cli_instance.execute(
                    "gcloud firestore databases describe "
                    f" --database='{database_name}' "
                    " --format='json'"
                )

            except RuntimeError as e:

                if "NOT_FOUND" in str(e):

                    """
                    Allocate a new Firestore database, in datastore mode
                    """

                    self.logging.info(f"Allocating a new Firestore database {database_name}")
                    self._cli_instance.execute(
                        "gcloud firestore databases create "
                        f" --database='{database_name}' "
                        f" --location={self.region} "
                        f" --type='datastore-mode' "
                    )
                    self.logging.info(f"Allocated a new Firestore database {database_name}")

                else:

                    self.logging.error("Couldn't query Datastore instances!")
                    self.logging.error(e)
                    raise RuntimeError("Couldn't query Datastore instances!")

            db_client = datastore.Client(database=database_name)
            benchmark_resources = BenchmarkResources(
                database=database_name, kinds=[], database_client=db_client
            )
            self._benchmark_resources[benchmark] = benchmark_resources

        benchmark_resources.kinds.append(name)

        return name

    def clear_table(self, name: str) -> str:
        """Clear all entities from a table.

        Args:
            name: Name of the table to clear

        Returns:
            Table name

        Raises:
            NotImplementedError: This method is not yet implemented
        """
        raise NotImplementedError()

    def remove_table(self, name: str) -> str:
        """Remove a table from the database.

        Args:
            name: Name of the table to remove

        Returns:
            Table name

        Raises:
            NotImplementedError: This method is not yet implemented
        """
        raise NotImplementedError()
