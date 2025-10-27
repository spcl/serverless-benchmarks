"""AWS DynamoDB NoSQL storage implementation for SeBS.

This module provides the DynamoDB class which implements NoSQL storage functionality
for the Serverless Benchmarking Suite using Amazon DynamoDB. It handles table
creation, data operations, and caching for benchmark data storage.

Key classes:
    DynamoDB: AWS DynamoDB NoSQL storage implementation
"""

from collections import defaultdict
from typing import Dict, Optional, Tuple

from sebs.cache import Cache
from sebs.faas.config import Resources
from sebs.faas.nosql import NoSQLStorage

import boto3
from boto3.dynamodb.types import TypeSerializer


class DynamoDB(NoSQLStorage):
    """AWS DynamoDB NoSQL storage implementation for SeBS.

    This class provides NoSQL storage functionality using Amazon DynamoDB.
    It handles table creation, data operations, caching, and provides a
    unified interface for benchmark data storage.

    Attributes:
        client: DynamoDB client for AWS API operations
        _tables: Mapping of benchmark names to table configurations
        _serializer: DynamoDB type serializer for data conversion
    """

    @staticmethod
    def typename() -> str:
        """Get the type name for this storage system.

        Returns:
            str: Type name ('AWS.DynamoDB')
        """
        return "AWS.DynamoDB"

    @staticmethod
    def deployment_name() -> str:
        """Get the deployment name for this storage system.

        Returns:
            str: Deployment name ('aws')
        """
        return "aws"

    def __init__(
        self,
        session: boto3.session.Session,
        cache_client: Cache,
        resources: Resources,
        region: str,
        access_key: str,
        secret_key: str,
    ) -> None:
        """Initialize DynamoDB NoSQL storage.

        Args:
            session: AWS boto3 session
            cache_client: Cache client for storing table configurations
            resources: Cloud resource configuration
            region: AWS region name
            access_key: AWS access key ID
            secret_key: AWS secret access key
        """
        super().__init__(region, cache_client, resources)
        self.client = session.client(
            "dynamodb",
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

        # Map benchmark -> name used by benchmark -> actual table_name in AWS
        # Example "shopping_cart" -> "sebs-benchmarks-<resource-id>-130.crud-api-shopping_cart"
        self._tables: Dict[str, Dict[str, str]] = defaultdict(dict)

        self._serializer = TypeSerializer()

    def retrieve_cache(self, benchmark: str) -> bool:
        """Retrieve table configuration from cache.

        Args:
            benchmark: Name of the benchmark

        Returns:
            bool: True if cache was found and loaded, False otherwise
        """
        if benchmark in self._tables:
            return True

        cached_storage = self.cache_client.get_nosql_config(self.deployment_name(), benchmark)
        if cached_storage is not None:
            self._tables[benchmark] = cached_storage["tables"]
            return True

        return False

    def update_cache(self, benchmark: str) -> None:
        """Update cache with current table configuration.

        Args:
            benchmark: Name of the benchmark to update cache for
        """
        self._cache_client.update_nosql(
            self.deployment_name(),
            benchmark,
            {
                "tables": self._tables[benchmark],
            },
        )

    def get_tables(self, benchmark: str) -> Dict[str, str]:
        """Get table mappings for a benchmark.

        Args:
            benchmark: Name of the benchmark

        Returns:
            Dict[str, str]: Mapping of logical table names to actual DynamoDB table names
        """
        return self._tables[benchmark]

    def _get_table_name(self, benchmark: str, table: str) -> Optional[str]:
        """Get the actual DynamoDB table name for a logical table.

        Args:
            benchmark: Name of the benchmark
            table: Logical table name used by the benchmark

        Returns:
            Optional[str]: Actual DynamoDB table name, or None if not found
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
        data: dict,
        primary_key: Tuple[str, str],
        secondary_key: Optional[Tuple[str, str]] = None,
    ) -> None:
        """Write data to a DynamoDB table.

        Args:
            benchmark: Name of the benchmark
            table: Logical table name
            data: Data to write to the table
            primary_key: Primary key as (attribute_name, value) tuple
            secondary_key: Optional secondary key as (attribute_name, value) tuple

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
        """Create a DynamoDB table for benchmark data.

        Creates a unique DynamoDB table name using resource ID, benchmark name, and provided name.
        Unlike Azure (account -> database -> container) and GCP (database per benchmark),
        AWS requires unique table names across the account.

        The function handles cases where the table already exists or is being created.
        Uses PAY_PER_REQUEST billing mode.

        Args:
            benchmark: Name of the benchmark
            name: Logical table name
            primary_key: Name of the primary key attribute
            secondary_key: Optional name of the secondary key attribute

        Returns:
            str: Name of the created table

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
                waiter.wait(TableName=table_name, WaiterConfig={"Delay": 1})

            self.logging.info(f"Created DynamoDB table {name} for benchmark {benchmark}")
            self._tables[benchmark][name] = table_name

            return ret["TableDescription"]["TableName"]

        except self.client.exceptions.ResourceInUseException as e:

            if "already exists" in e.response["Error"]["Message"]:

                # We need this waiter.
                # Otheriwise, we still might get later `ResourceNotFoundException`
                # when uploading benchmark data.
                self.logging.info(f"Waiting for the existing table {table_name} to be created")
                waiter = self.client.get_waiter("table_exists")
                waiter.wait(TableName=table_name, WaiterConfig={"Delay": 1})
                ret = self.client.describe_table(TableName=table_name)

                self.logging.info(
                    f"Using existing DynamoDB table {table_name} for benchmark {benchmark}"
                )
                self._tables[benchmark][name] = table_name
                return name

            if "being created" in e.response["Error"]["Message"]:

                self.logging.info(f"Waiting for the existing table {table_name} to be created")
                waiter = self.client.get_waiter("table_exists")
                waiter.wait(TableName=table_name, WaiterConfig={"Delay": 1})
                ret = self.client.describe_table(TableName=table_name)

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
            str: Result of the operation

        Raises:
            NotImplementedError: This operation is not yet implemented
        """
        raise NotImplementedError()

    def remove_table(self, name: str) -> str:
        """Remove a table completely.

        Args:
            name: Name of the table to remove

        Returns:
            str: Result of the operation

        Raises:
            NotImplementedError: This operation is not yet implemented
        """
        raise NotImplementedError()
