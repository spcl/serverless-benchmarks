"""ScyllaDB NoSQL storage implementation for the Serverless Benchmarking Suite.

This module implements NoSQL database storage using ScyllaDB, which provides a
DynamoDB-compatible API through its Alternator interface. ScyllaDB runs in a
Docker container and provides high-performance NoSQL storage for benchmark data
that requires DynamoDB-compatible operations.

The implementation uses boto3 with ScyllaDB's Alternator API to provide seamless
compatibility with DynamoDB operations while running locally for development
and testing purposes.
"""

import json
import os
import platform
import time
from collections import defaultdict
from typing import Any, Dict, Optional, Tuple, Type, TypeVar

import boto3
from boto3.dynamodb.types import TypeSerializer
import docker

from sebs.cache import Cache
from sebs.faas.config import Resources
from sebs.faas.nosql import NoSQLStorage
from sebs.types import NoSQLStorage as StorageType
from sebs.storage.config import ScyllaDBConfig
from sebs.utils import project_absolute_path


class ScyllaDB(NoSQLStorage):
    """ScyllaDB implementation for DynamoDB-compatible NoSQL storage.

    This class manages a ScyllaDB instance running in a Docker container,
    providing DynamoDB-compatible NoSQL storage through ScyllaDB's Alternator
    interface. It handles table creation, data operations, and container
    lifecycle management.

    Attributes:
        _docker_client: Docker client for container management
        _storage_container: Docker container running ScyllaDB
        _cfg: ScyllaDB configuration settings
        _tables: Mapping of benchmark names to table mappings
        _serializer: DynamoDB type serializer for data conversion
        client: Boto3 DynamoDB client configured for ScyllaDB
    """

    @staticmethod
    def typename() -> str:
        """Get the qualified type name of this class.

        Returns:
            str: Full type name including deployment name
        """
        return f"{ScyllaDB.deployment_name()}.ScyllaDB"

    @staticmethod
    def deployment_name() -> str:
        """Get the deployment platform name.

        Returns:
            str: Deployment name ('scylladb')
        """
        return "scylladb"

    @property
    def config(self) -> ScyllaDBConfig:
        """Get the ScyllaDB configuration.

        Returns:
            ScyllaDBConfig: The configuration object
        """
        return self._cfg

    # The region setting is required by DynamoDB API but not used for local ScyllaDB
    SCYLLADB_REGION = "None"

    def __init__(
        self,
        docker_client: docker.DockerClient,
        cache_client: Cache,
        config: ScyllaDBConfig,
        resources: Optional[Resources] = None,
    ):
        """Initialize a ScyllaDB storage instance.

        Args:
            docker_client: Docker client for managing the ScyllaDB container
            cache_client: Cache client for storing storage configuration
            config: ScyllaDB configuration settings
            resources: Resources configuration (optional)
        """
        super().__init__(self.SCYLLADB_REGION, cache_client, resources)  # type: ignore
        self._docker_client = docker_client
        self._storage_container: Optional[docker.models.containers.Container] = None
        self._cfg = config

        # Map benchmark -> orig_name -> table_name
        self._tables: Dict[str, Dict[str, str]] = defaultdict(dict)
        self._serializer = TypeSerializer()

        if config.address != "":
            self.client = boto3.client(
                "dynamodb",
                region_name="None",
                aws_access_key_id="None",
                aws_secret_access_key="None",
                endpoint_url=f"http://{config.address}",
            )

    def start(self) -> None:
        """Start a ScyllaDB storage container.

        Creates and runs a Docker container with ScyllaDB, configuring it with
        the specified CPU and memory resources. The container runs in detached
        mode and exposes the Alternator DynamoDB-compatible API on the configured port.

        The method waits for ScyllaDB to fully initialize by checking the nodetool
        status until the service is ready.

        Raises:
            RuntimeError: If starting the ScyllaDB container fails or if ScyllaDB
                         fails to initialize within the timeout period
        """
        if self._cfg.data_volume == "":
            scylladb_volume = os.path.join(project_absolute_path(), "scylladb-volume")
        else:
            scylladb_volume = self._cfg.data_volume
        scylladb_volume = os.path.abspath(scylladb_volume)

        os.makedirs(scylladb_volume, exist_ok=True)
        volumes = {
            scylladb_volume: {
                "bind": "/var/lib/scylla/",
                "mode": "rw",
            }
        }

        try:
            scylladb_args = ""
            scylladb_args += f"--smp {self._cfg.cpus} "
            scylladb_args += f"--memory {self._cfg.memory}M "
            scylladb_args += "--overprovisioned 1 "
            scylladb_args += "--alternator-port 8000 "
            scylladb_args += "--alternator-write-isolation=only_rmw_uses_lwt "

            self.logging.info("Starting ScyllaDB storage")
            self._storage_container = self._docker_client.containers.run(
                f"scylladb/scylla:{self._cfg.version}",
                command=scylladb_args,
                name="some-scylla",
                hostname="some-scylla",
                network_mode="bridge",
                volumes=volumes,
                ports={"8000": str(self._cfg.mapped_port)},
                remove=True,
                stdout=True,
                stderr=True,
                detach=True,
            )
            self._cfg.instance_id = self._storage_container.id

            # Wait until it boots up
            attempts = 0
            max_attempts = 30
            while attempts < max_attempts:
                exit_code, out = self._storage_container.exec_run("nodetool status")

                if exit_code == 0:
                    self.logging.info("Started ScyllaDB successfully!")
                    break

                time.sleep(1.0)
                attempts += 1

            if attempts == max_attempts:
                self.logging.error("Failed to launch ScyllaDB!")
                self.logging.error(f"Last result of nodetool status: {out}")
                raise RuntimeError("Failed to launch ScyllaDB!")

            self.configure_connection()
        except docker.errors.APIError as e:
            self.logging.error("Starting ScyllaDB storage failed! Reason: {}".format(e))
            raise RuntimeError("Starting ScyllaDB storage unsuccessful")
        except Exception as e:
            self.logging.error("Starting ScyllaDB storage failed! Unknown error: {}".format(e))
            raise RuntimeError("Starting ScyllaDB storage unsuccessful")

    def configure_connection(self) -> None:
        """Configure the connection to the ScyllaDB container.

        Determines the appropriate address to connect to the ScyllaDB container
        based on the host platform. For Linux, it uses the container's IP address,
        while for Windows, macOS, or WSL it uses localhost with the mapped port.

        Creates a boto3 DynamoDB client configured to connect to ScyllaDB's
        Alternator interface.

        Raises:
            RuntimeError: If the ScyllaDB container is not available or if the IP address
                          cannot be detected
        """
        if self._cfg.address == "":
            if self._storage_container is None:
                raise RuntimeError(
                    "ScyllaDB container is not available! Make sure that you deployed "
                    "the ScyllaDB storage and provided configuration!"
                )

            self._storage_container.reload()

            # Check if the system is Linux and that it's not WSL
            if platform.system() == "Linux" and "microsoft" not in platform.release().lower():
                networks = self._storage_container.attrs["NetworkSettings"]["Networks"]
                self._cfg.address = "{IPAddress}:{Port}".format(
                    IPAddress=networks["bridge"]["IPAddress"], Port=self._cfg.alternator_port
                )
            else:
                # System is either WSL, Windows, or Mac
                self._cfg.address = f"localhost:{self._cfg.mapped_port}"

            if not self._cfg.address:
                self.logging.error(
                    f"Couldn't read the IP address of container from attributes "
                    f"{json.dumps(self._storage_container.attrs, indent=2)}"
                )
                raise RuntimeError(
                    f"Incorrect detection of IP address for container with id {self._cfg.instance_id}"
                )
            self.logging.info("Starting ScyllaDB instance at {}".format(self._cfg.address))

        # Create the DynamoDB client for ScyllaDB's Alternator interface
        self.client = boto3.client(
            "dynamodb",
            region_name="None",
            aws_access_key_id="None",
            aws_secret_access_key="None",
            endpoint_url=f"http://{self._cfg.address}",
        )

    def stop(self) -> None:
        """Stop the ScyllaDB container.

        Gracefully stops the running ScyllaDB container if it exists.
        Logs an error if the container is not known.
        """
        if self._storage_container is not None:
            self.logging.info(f"Stopping ScyllaDB container at {self._cfg.address}.")
            self._storage_container.stop()
            self.logging.info(f"Stopped ScyllaDB container at {self._cfg.address}.")
        else:
            self.logging.error("Stopping ScyllaDB was not successful, storage container not known!")

    def envs(self) -> Dict[str, str]:
        """Generate environment variables for ScyllaDB configuration.

        Creates environment variables that can be used by benchmark functions
        to connect to the ScyllaDB storage instance.

        Returns:
            Dict[str, str]: Environment variables for ScyllaDB connection
        """
        return {"NOSQL_STORAGE_TYPE": "scylladb", "NOSQL_STORAGE_ENDPOINT": self._cfg.address}

    def serialize(self) -> Tuple[StorageType, Dict[str, Any]]:
        """Serialize ScyllaDB configuration to a tuple.

        Returns:
            Tuple[StorageType, Dict[str, Any]]: Storage type and serialized configuration
        """
        return StorageType.SCYLLADB, self._cfg.serialize()

    # Deserialization and inheritance support
    #
    # This implementation supports overriding this class. The main ScyllaDB class
    # is used to start/stop deployments. When overriding the implementation in
    # Local/OpenWhisk/..., we call the _deserialize method and provide an
    # alternative implementation type.

    T = TypeVar("T", bound="ScyllaDB")

    @staticmethod
    def _deserialize(
        cached_config: ScyllaDBConfig, cache_client: Cache, resources: Resources, obj_type: Type[T]
    ) -> T:
        """Deserialize a ScyllaDB instance from cached configuration with custom type.

        Creates a new instance of the specified class type from cached configuration
        data. This allows platform-specific versions to be deserialized correctly
        while sharing the core implementation.

        Args:
            cached_config: Cached ScyllaDB configuration
            cache_client: Cache client
            resources: Resources configuration
            obj_type: Type of object to create (a ScyllaDB subclass)

        Returns:
            T: Deserialized instance of the specified type

        Raises:
            RuntimeError: If the storage container does not exist
        """
        docker_client = docker.from_env()
        obj = obj_type(docker_client, cache_client, cached_config, resources)

        if cached_config.instance_id:
            instance_id = cached_config.instance_id
            try:
                obj._storage_container = docker_client.containers.get(instance_id)
            except docker.errors.NotFound:
                raise RuntimeError(f"Storage container {instance_id} does not exist!")
        else:
            obj._storage_container = None
        return obj

    @staticmethod
    def deserialize(
        cached_config: ScyllaDBConfig, cache_client: Cache, resources: Resources
    ) -> "ScyllaDB":
        """Deserialize a ScyllaDB instance from cached configuration.

        Creates a new ScyllaDB instance from cached configuration data.

        Args:
            cached_config: Cached ScyllaDB configuration
            cache_client: Cache client
            resources: Resources configuration

        Returns:
            ScyllaDB: Deserialized ScyllaDB instance
        """
        return ScyllaDB._deserialize(cached_config, cache_client, resources, ScyllaDB)

    def retrieve_cache(self, benchmark: str) -> bool:
        """Retrieve cached table configuration for a benchmark.

        Checks if table configuration for the given benchmark is already loaded
        in memory, and if not, attempts to load it from the cache.

        Args:
            benchmark: Name of the benchmark

        Returns:
            bool: True if table configuration was found, False otherwise
        """
        if benchmark in self._tables:
            return True

        cached_storage = self.cache_client.get_nosql_config(self.deployment_name(), benchmark)
        if cached_storage is not None:
            self._tables[benchmark] = cached_storage["tables"]
            return True

        return False

    def update_cache(self, benchmark: str) -> None:
        """Update the cache with table configuration for a benchmark.

        Stores the table configuration for the specified benchmark in the cache
        for future retrieval.

        Args:
            benchmark: Name of the benchmark
        """
        self._cache_client.update_nosql(
            self.deployment_name(),
            benchmark,
            {
                "tables": self._tables[benchmark],
            },
        )

    def get_tables(self, benchmark: str) -> Dict[str, str]:
        """Get the table name mappings for a benchmark.

        Args:
            benchmark: Name of the benchmark

        Returns:
            Dict[str, str]: Mapping from original table names to actual table names
        """
        return self._tables[benchmark]

    def _get_table_name(self, benchmark: str, table: str) -> Optional[str]:
        """Get the actual table name for a benchmark's logical table name.

        Args:
            benchmark: Name of the benchmark
            table: Logical table name

        Returns:
            Optional[str]: Actual table name or None if not found
        """
        if benchmark not in self._tables:
            return None

        if table not in self._tables[benchmark]:
            return None

        return self._tables[benchmark][table]

    def write_to_table(
        self,
        benchmark: str,
        table: str,
        data: Dict[str, Any],
        primary_key: Tuple[str, str],
        secondary_key: Optional[Tuple[str, str]] = None,
    ) -> None:
        """Write data to a DynamoDB table in ScyllaDB.

        Serializes the data using DynamoDB type serialization and writes it
        to the specified table with the provided primary and optional secondary keys.

        Args:
            benchmark: Name of the benchmark
            table: Logical table name
            data: Data to write to the table
            primary_key: Tuple of (key_name, key_value) for the primary key
            secondary_key: Optional tuple of (key_name, key_value) for the secondary key

        Raises:
            AssertionError: If the table name is not found
        """
        table_name = self._get_table_name(benchmark, table)
        assert table_name is not None

        for key in (primary_key, secondary_key):
            if key is not None:
                data[key[0]] = key[1]

        serialized_data = {k: self._serializer.serialize(v) for k, v in data.items()}
        self.client.put_item(TableName=table_name, Item=serialized_data)

    def create_table(
        self, benchmark: str, name: str, primary_key: str, secondary_key: Optional[str] = None
    ) -> str:
        """Create a DynamoDB table in ScyllaDB.

        Creates a new DynamoDB table with the specified primary key and optional
        secondary key. The table name is constructed to be unique across benchmarks
        and resource groups.

        Note: Unlike cloud providers with hierarchical database structures,
        ScyllaDB requires unique table names at the cluster level.

        Args:
            benchmark: Name of the benchmark
            name: Logical table name
            primary_key: Name of the primary key attribute
            secondary_key: Optional name of the secondary key attribute

        Returns:
            str: The actual table name that was created

        Raises:
            RuntimeError: If table creation fails for unknown reasons
        """
        table_name = f"sebs-benchmarks-{self._cloud_resources.resources_id}-{benchmark}-{name}"

        try:
            definitions = [{"AttributeName": primary_key, "AttributeType": "S"}]
            key_schema = [{"AttributeName": primary_key, "KeyType": "HASH"}]

            if secondary_key is not None:
                definitions.append({"AttributeName": secondary_key, "AttributeType": "S"})
                key_schema.append({"AttributeName": secondary_key, "KeyType": "RANGE"})

            ret = self.client.create_table(
                TableName=table_name,
                BillingMode="PAY_PER_REQUEST",
                AttributeDefinitions=definitions,  # type: ignore
                KeySchema=key_schema,  # type: ignore
            )

            if ret["TableDescription"]["TableStatus"] == "CREATING":
                self.logging.info(f"Waiting for creation of DynamoDB table {name}")
                waiter = self.client.get_waiter("table_exists")
                waiter.wait(TableName=name)

            self.logging.info(f"Created DynamoDB table {name} for benchmark {benchmark}")
            self._tables[benchmark][name] = table_name

            return ret["TableDescription"]["TableName"]

        except self.client.exceptions.ResourceInUseException as e:
            if "already exists" in e.response["Error"]["Message"]:
                self.logging.info(
                    f"Using existing DynamoDB table {table_name} for benchmark {benchmark}"
                )
                self._tables[benchmark][name] = table_name
                return name

            raise RuntimeError(f"Creating DynamoDB failed, unknown reason! Error: {e}")

    def clear_table(self, name: str) -> str:
        """Clear all data from a table.

        Args:
            name: Name of the table to clear

        Returns:
            str: Table name

        Raises:
            NotImplementedError: This method is not yet implemented
        """
        raise NotImplementedError()

    def remove_table(self, name: str) -> str:
        """Remove a table completely.

        Args:
            name: Name of the table to remove

        Returns:
            str: Table name

        Raises:
            NotImplementedError: This method is not yet implemented
        """
        raise NotImplementedError()
