import json
import os
import platform
import time
from collections import defaultdict
from typing import Dict, Optional, Tuple, Type, TypeVar

from sebs.cache import Cache
from sebs.faas.config import Resources
from sebs.faas.nosql import NoSQLStorage
from sebs.types import NoSQLStorage as StorageType
from sebs.storage.config import ScyllaDBConfig
from sebs.utils import project_absolute_path

import boto3
from boto3.dynamodb.types import TypeSerializer
import docker


class ScyllaDB(NoSQLStorage):
    """
    NoSQL storage implementation using a self-hosted ScyllaDB server
    running in a Docker container. ScyllaDB is accessed via its DynamoDB-compatible
    API (Alternator).
    """
    @staticmethod
    def typename() -> str:
        """Return the type name of this storage implementation."""
        return f"{ScyllaDB.deployment_name()}.ScyllaDB"

    @staticmethod
    def deployment_name() -> str:
        """Return the deployment name, which is 'scylladb' for this storage type."""
        return "scylladb"

    @property
    def config(self) -> ScyllaDBConfig:
        """The ScyllaDB specific configuration for this storage instance."""
        return self._cfg

    # ScyllaDB is self-hosted, so a fixed region is used, though not strictly applicable.
    SCYLLADB_REGION = "None"

    def __init__(
        self,
        docker_client: docker.client,
        cache_client: Cache,
        config: ScyllaDBConfig,
        resources: Optional[Resources] = None, # Should be SelfHostedResources for consistency
    ):
        """
        Initialize the ScyllaDB storage client.

        Sets up connection parameters and initializes a boto3 DynamoDB client
        configured to connect to ScyllaDB's Alternator endpoint if an address is provided.

        :param docker_client: Docker client instance for managing the ScyllaDB container.
        :param cache_client: Cache client instance.
        :param config: ScyllaDBConfig object with connection and deployment details.
        :param resources: Cloud/system resources configuration object.
        """
        super().__init__(self.SCYLLADB_REGION, cache_client, resources) # type: ignore
        self._docker_client = docker_client
        self._storage_container: Optional[docker.models.containers.Container] = None # Type hint
        self._cfg = config

        # Map benchmark -> original_table_name -> actual_table_name (used by parent, might be direct here)
        self._tables: Dict[str, Dict[str, str]] = defaultdict(dict)
        self._serializer = TypeSerializer() # For DynamoDB data types

        # Initialize boto3 client if address is already known (e.g. from cache)
        if config.address: # Check if address is not empty
            self.client = boto3.client( # This is a DynamoDB client
                "dynamodb",
                region_name=self.SCYLLADB_REGION, # ScyllaDB region is 'None'
                aws_access_key_id=config.access_key, # Should be config.access_key
                aws_secret_access_key=config.secret_key, # Should be config.secret_key
                endpoint_url=f"http://{config.address}:{config.alternator_port}", # Use alternator_port
            )
        else:
            self.client = None # Will be initialized after container start and IP detection

    def start(self):
        """
        Start the ScyllaDB Docker container.

        Configures a data volume, CPU/memory resources, and ScyllaDB arguments
        (including enabling Alternator). Waits for the node to become operational.
        The container ID and connection details are stored in `self._cfg`.

        :raises RuntimeError: If starting the ScyllaDB container fails or node doesn't boot.
        """
        if not self._cfg.data_volume: # Check if data_volume is empty or None
            scylla_data_path = os.path.join(project_absolute_path(), "scylladb-volume")
        else:
            scylla_data_path = self._cfg.data_volume
        scylla_data_path = os.path.abspath(scylla_data_path)
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
                    self.logging.info("Started ScyllaDB succesfully!")
                    break

                time.sleep(1.0)
                attempts += 1

            if attempts == max_attempts:
                self.logging.error("Failed to launch ScyllaBD!")
                self.logging.error(f"Last result of nodetool status: {out}")
                raise RuntimeError("Failed to launch ScyllaBD!")

            self.configure_connection()
        except docker.errors.APIError as e:
            self.logging.error("Starting ScyllaDB storage failed! Reason: {}".format(e))
            raise RuntimeError("Starting ScyllaDB storage unsuccesful")
        except Exception as e:
            self.logging.error("Starting ScyllaDB storage failed! Unknown error: {}".format(e))
            raise RuntimeError("Starting ScyllaDB storage unsuccesful")

    def configure_connection(self):
        """
        Configure the connection details (address) for the ScyllaDB client (Alternator endpoint).

        If the address is not already set in the config, it determines the
        ScyllaDB server address based on the Docker container's network settings.
        On Linux, it uses the container's bridge IP and the Alternator port.
        On other systems, it uses localhost with the host-mapped Alternator port.
        Initializes `self.client` with a boto3 DynamoDB client instance.

        :raises RuntimeError: If the ScyllaDB container is not running or IP address cannot be detected.
        """
        # The original comment "who knows why? otherwise attributes are not loaded"
        # likely refers to needing to call reload() or access attrs to populate them.
        if not self._cfg.address: # Check if address is empty or None
            if self._storage_container is None:
                raise RuntimeError(
                    "ScyllaDB container is not available! Ensure ScyllaDB is started and configured."
                )
            self._storage_container.reload() # Refresh container attributes

            if platform.system() == "Linux" and "microsoft" not in platform.release().lower(): # Native Linux
                networks = self._storage_container.attrs.get("NetworkSettings", {}).get("Networks", {})
                bridge_network = networks.get("bridge", {})
                ip_address = bridge_network.get("IPAddress")
                if not ip_address: # Fallback for some Docker versions or network modes
                    ip_address = bridge_network.get("Gateway")
                if not ip_address:
                    self.logging.error(
                        "Could not determine ScyllaDB container IP address from bridge network. Attributes: %s",
                        json.dumps(self._storage_container.attrs, indent=2)
                    )
                    raise RuntimeError(f"Failed to detect IP address for ScyllaDB container {self._storage_container.id}")
                # Use the internal alternator port for connection from host if bridge IP is used
                self._cfg.address = f"{ip_address}:{self._cfg.alternator_port}"
            else: # Docker Desktop (Windows, macOS), WSL
                # Use the host-mapped port for Alternator
                if self._cfg.mapped_port == -1: # mapped_port should be for Alternator here
                    raise RuntimeError("ScyllaDB Alternator host port not mapped or invalid for non-Linux Docker.")
                self._cfg.address = f"localhost:{self._cfg.mapped_port}"
            
            self.logging.info(f"ScyllaDB (Alternator) instance configured at http://{self._cfg.address}")

        # Initialize boto3 client to interact with ScyllaDB's DynamoDB API (Alternator)
        # This should be done after the address (and potentially port for Alternator) is known.
        self.client = boto3.client(
            "dynamodb",
            region_name=self.SCYLLADB_REGION,
            aws_access_key_id=self._cfg.access_key, # Use configured keys
            aws_secret_access_key=self._cfg.secret_key,
            endpoint_url=f"http://{self._cfg.address}", # Full endpoint URL
        )


    def stop(self):
        """
        Stop the ScyllaDB Docker container if it's running.
        """
        if self._storage_container is not None:
            try:
                self.logging.info(f"Stopping ScyllaDB container {self._storage_container.id} at {self._cfg.address}.")
                self._storage_container.stop()
                self.logging.info(f"Stopped ScyllaDB container {self._storage_container.id}.")
            except docker.errors.NotFound:
                self.logging.warning(f"ScyllaDB container {self._storage_container.id} already removed or not found.")
            except docker.errors.APIError as e:
                self.logging.error(f"Error stopping ScyllaDB container {self._storage_container.id}: {e}")
        else:
            self.logging.warning("Attempted to stop ScyllaDB, but storage container instance is not known.")

    def envs(self) -> dict:
        """
        Return environment variables for functions to connect to this ScyllaDB instance
        via its Alternator (DynamoDB compatible) endpoint.

        :return: Dictionary of ScyllaDB Alternator related environment variables.
        """
        # Ensure address includes the Alternator port if not already part of it
        # self.configure_connection() might be needed if address wasn't set before envs() is called
        if not self._cfg.address:
            self.configure_connection() # Ensure address is resolved
            
        return {
            "NOSQL_STORAGE_TYPE": "scylladb", # Or "dynamodb" if functions use generic DynamoDB SDK
            "NOSQL_STORAGE_ENDPOINT": f"http://{self._cfg.address}", # Full endpoint URL
            # ScyllaDB's Alternator might not require AWS_ACCESS_KEY_ID/SECRET if auth is off
            # If needed, they would be self._cfg.access_key and self._cfg.secret_key
            "AWS_ACCESS_KEY_ID": self._cfg.access_key,
            "AWS_SECRET_ACCESS_KEY": self._cfg.secret_key,
            "AWS_DEFAULT_REGION": self.SCYLLADB_REGION, # Needs a region for AWS SDK
        }

    def serialize(self) -> Tuple[StorageType, dict]:
        """
        Serialize the ScyllaDB storage configuration.

        :return: Tuple containing the storage type (StorageType.SCYLLADB) and
                 the serialized ScyllaDBConfig dictionary.
        """
        return StorageType.SCYLLADB, self._cfg.serialize()

    T = TypeVar("T", bound="ScyllaDB") # For type hinting the return of _deserialize

    @staticmethod
    def _deserialize(
        cached_config: ScyllaDBConfig,
        cache_client: Cache,
        resources: Resources, # Should be SelfHostedResources
        obj_type: Type[T], # The concrete class type (ScyllaDB or subclass)
    ) -> T:
        """
        Internal helper to deserialize a ScyllaDB (or subclass) instance.

        Restores configuration and re-attaches to an existing Docker container if specified.

        :param cached_config: The ScyllaDBConfig object from cache/config.
        :param cache_client: Cache client instance.
        :param resources: The Resources object.
        :param obj_type: The actual class type to instantiate.
        :return: An instance of `obj_type`.
        :raises RuntimeError: If a cached Docker container ID is provided but the container is not found.
        """
        docker_client = docker.from_env()
        # Create instance of the correct type, passing all necessary args
        obj = obj_type(docker_client, cache_client, cached_config, resources)
        # obj._cfg is already set by __init__

        if cached_config.instance_id: # If a container ID was cached
            try:
                obj._storage_container = docker_client.containers.get(cached_config.instance_id)
                obj.logging.info(f"Re-attached to existing ScyllaDB container {cached_config.instance_id}")
            except docker.errors.NotFound:
                obj.logging.error(f"Cached ScyllaDB container {cached_config.instance_id} not found!")
                raise RuntimeError(f"ScyllaDB storage container {cached_config.instance_id} does not exist!")
            except docker.errors.APIError as e:
                obj.logging.error(f"API error attaching to ScyllaDB container {cached_config.instance_id}: {e}")
                raise
        else:
            obj._storage_container = None # No cached container ID
        
        # Configure connection if address is known (either from config or after container reload)
        if obj._cfg.address or obj._storage_container:
            obj.configure_connection()
            
        return obj

    @staticmethod
    def deserialize(
        cached_config: ScyllaDBConfig, cache_client: Cache, resources: Resources
    ) -> "ScyllaDB":
        """
        Deserialize a ScyllaDB instance from a ScyllaDBConfig object.

        :param cached_config: The ScyllaDBConfig object.
        :param cache_client: Cache client instance.
        :param resources: The Resources object.
        :return: A ScyllaDB instance.
        """
        return ScyllaDB._deserialize(cached_config, cache_client, resources, ScyllaDB)

    def retrieve_cache(self, benchmark: str) -> bool:
        """
        Retrieve ScyllaDB table configurations for a benchmark from the cache.

        Populates internal table mappings if cached data is found.

        :param benchmark: The name of the benchmark.
        :return: True if cached data was successfully retrieved, False otherwise.
        """
        if benchmark in self._tables:
            return True
        cached_storage_info = self.cache_client.get_nosql_config(self.deployment_name(), benchmark)
        if cached_storage_info and "tables" in cached_storage_info:
            self._tables[benchmark] = cached_storage_info["tables"]
            return True
        return False

    def update_cache(self, benchmark: str):
        """
        Update the cache with the current ScyllaDB table configurations for a benchmark.

        :param benchmark: The name of the benchmark.
        """
        self._cache_client.update_nosql(
            self.deployment_name(),
            benchmark,
            {"tables": self._tables[benchmark]}, # Store the table mappings
        )

    def get_tables(self, benchmark: str) -> Dict[str, str]:
        """
        Get the mapping of benchmark-defined table names to actual ScyllaDB/DynamoDB table names.

        :param benchmark: Name of the benchmark.
        :return: Dictionary mapping logical table names to actual table names.
        """
        return self._tables[benchmark]

    def _get_table_name(self, benchmark: str, table_alias: str) -> Optional[str]: # Renamed arg
        """
        Get the actual cloud provider table name for a given benchmark and logical table alias.

        :param benchmark: The name of the benchmark.
        :param table_alias: The logical name of the table within the benchmark.
        :return: The actual table name, or None if not found.
        """
        benchmark_tables = self._tables.get(benchmark)
        if benchmark_tables:
            return benchmark_tables.get(table_alias)
        return None

    def write_to_table(
        self,
        benchmark: str,
        table_alias: str, # Renamed from table to table_alias
        data: dict,
        primary_key: Tuple[str, str], # (key_name, key_value)
        secondary_key: Optional[Tuple[str, str]] = None, # (key_name, key_value)
    ):
        """
        Write an item to the specified ScyllaDB/DynamoDB table.

        Data is serialized using DynamoDB TypeSerializer.

        :param benchmark: The name of the benchmark.
        :param table_alias: The logical name of the table.
        :param data: The data to write (as a dictionary).
        :param primary_key: Tuple (key_name, key_value) for the primary/partition key.
        :param secondary_key: Optional tuple for the secondary/sort key.
        """
        actual_table_name = self._get_table_name(benchmark, table_alias)
        assert actual_table_name is not None, f"Table alias {table_alias} not found for benchmark {benchmark}"

        item_to_put = data.copy() # Avoid modifying original data dict
        # Add primary and secondary keys to the item itself
        item_to_put[primary_key[0]] = primary_key[1]
        if secondary_key:
            item_to_put[secondary_key[0]] = secondary_key[1]
        
        serialized_item = {k: self._serializer.serialize(v) for k, v in item_to_put.items()}
        if not self.client:
            self.configure_connection() # Ensure client is initialized
        self.client.put_item(TableName=actual_table_name, Item=serialized_item) # type: ignore


    def create_table(
        self, benchmark: str, name_alias: str, primary_key_name: str, secondary_key_name: Optional[str] = None
    ) -> str:
        """
        Create a ScyllaDB/DynamoDB table for a benchmark.

        Table names are constructed using a standard SeBS pattern:
        `sebs-benchmarks-{resource_id}-{benchmark-name}-{table_alias}`.
        Uses PAY_PER_REQUEST billing mode (DynamoDB specific, ScyllaDB ignores).

        :param benchmark: Name of the benchmark.
        :param name_alias: Logical name for the table within the benchmark.
        :param primary_key_name: Name of the primary/partition key attribute.
        :param secondary_key_name: Optional name of the secondary/sort key attribute.
        :return: Actual name of the created or existing table.
        :raises RuntimeError: If table creation fails for an unknown reason.
        """
        # Construct the full table name
        actual_table_name = f"sebs-benchmarks-{self._cloud_resources.resources_id}-{benchmark}-{name_alias}"

        try:
            attribute_definitions = [{"AttributeName": primary_key_name, "AttributeType": "S"}] # Assume string keys
            key_schema = [{"AttributeName": primary_key_name, "KeyType": "HASH"}] # HASH for partition key

            if secondary_key_name:
                attribute_definitions.append({"AttributeName": secondary_key_name, "AttributeType": "S"})
                key_schema.append({"AttributeName": secondary_key_name, "KeyType": "RANGE"}) # RANGE for sort key
            
            if not self.client:
                self.configure_connection() # Ensure client is initialized

            response = self.client.create_table( # type: ignore
                TableName=actual_table_name,
                AttributeDefinitions=attribute_definitions,
                KeySchema=key_schema,
                BillingMode="PAY_PER_REQUEST" # For DynamoDB compatibility, ScyllaDB ignores
            )
            
            # Wait for table to become active (mainly for DynamoDB, ScyllaDB might be faster)
            # ScyllaDB might not have CREATING status or waiter, handle this gracefully.
            if response.get("TableDescription", {}).get("TableStatus") == "CREATING":
                self.logging.info(f"Waiting for creation of table {actual_table_name}")
                try:
                    waiter = self.client.get_waiter("table_exists") # type: ignore
                    waiter.wait(TableName=actual_table_name)
                except Exception as e: # Broad exception if waiter not supported or fails
                    self.logging.warning(f"Waiter for table {actual_table_name} failed or not supported (ScyllaDB?): {e}. Assuming table will be available.")
                    time.sleep(5) # Generic wait for ScyllaDB

            self.logging.info(f"Created/Verified table {actual_table_name} for benchmark {benchmark}")
            self._tables[benchmark][name_alias] = actual_table_name
            return actual_table_name

        except self.client.exceptions.ResourceInUseException: # type: ignore
            # Table already exists
            self.logging.info(
                f"Using existing table {actual_table_name} for benchmark {benchmark}, alias {name_alias}"
            )
            self._tables[benchmark][name_alias] = actual_table_name
            return actual_table_name
        except Exception as e: # Catch other potential errors
            self.logging.error(f"Creating table {actual_table_name} failed: {e}")
            raise RuntimeError(f"Creating table failed: {e}")


    def clear_table(self, name: str) -> str:
        """
        Clear all items from a ScyllaDB/DynamoDB table.

        Note: This method is not implemented. Efficiently clearing a table
        often involves deleting and recreating it, or scanning and batch deleting items.

        :param name: Actual name of the table in the cloud/DB.
        :raises NotImplementedError: This method is not yet implemented.
        """
        raise NotImplementedError("Clearing a ScyllaDB/DynamoDB table is not implemented yet.")

    def remove_table(self, name: str) -> str:
        """
        Remove/delete a ScyllaDB/DynamoDB table completely.

        Note: This method is not implemented.

        :param name: Actual name of the table in the cloud/DB.
        :raises NotImplementedError: This method is not yet implemented.
        """
        raise NotImplementedError("Removing a ScyllaDB/DynamoDB table is not implemented yet.")
