from collections import defaultdict
from typing import Dict, Optional, Tuple

from sebs.cache import Cache
from sebs.faas.config import Resources
from sebs.faas.nosql import NoSQLStorage

import boto3
from boto3.dynamodb.types import TypeSerializer


class DynamoDB(NoSQLStorage):
    """AWS DynamoDB NoSQL storage implementation."""
    @staticmethod
    def typename() -> str:
        """Return the type name of the NoSQL storage implementation."""
        return "AWS.DynamoDB"

    @staticmethod
    def deployment_name():
        """Return the deployment name for AWS (aws)."""
        return "aws"

    def __init__(
        self,
        session: boto3.session.Session,
        cache_client: Cache,
        resources: Resources,
        region: str,
        access_key: str,
        secret_key: str,
    ):
        """
        Initialize DynamoDB client and internal table mapping.

        :param session: Boto3 session.
        :param cache_client: Cache client instance.
        :param resources: Cloud resources configuration.
        :param region: AWS region.
        :param access_key: AWS access key ID.
        :param secret_key: AWS secret access key.
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
        """
        Retrieve table mapping for a benchmark from the cache.

        Populates the internal `_tables` mapping if cached data is found.

        :param benchmark: Name of the benchmark.
        :return: True if cache was retrieved, False otherwise.
        """
        if benchmark in self._tables:
            return True

        cached_storage = self.cache_client.get_nosql_config(self.deployment_name(), benchmark)
        if cached_storage is not None:
            self._tables[benchmark] = cached_storage["tables"]
            return True

        return False

    def update_cache(self, benchmark: str):
        """
        Update the cache with the current table mapping for a benchmark.

        :param benchmark: Name of the benchmark.
        """
        self._cache_client.update_nosql(
            self.deployment_name(),
            benchmark,
            {
                "tables": self._tables[benchmark],
            },
        )

    def get_tables(self, benchmark: str) -> Dict[str, str]:
        """
        Get the mapping of benchmark-specific table names to actual AWS table names.

        :param benchmark: Name of the benchmark.
        :return: Dictionary mapping benchmark table names to AWS table names.
        """
        return self._tables[benchmark]

    def _get_table_name(self, benchmark: str, table: str) -> Optional[str]:
        """
        Get the actual AWS table name for a given benchmark and table alias.

        :param benchmark: Name of the benchmark.
        :param table: Alias of the table used within the benchmark.
        :return: Actual AWS table name, or None if not found.
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
    ):
        """
        Write data to a DynamoDB table.

        Serializes data using TypeSerializer before writing.

        :param benchmark: Name of the benchmark.
        :param table: Alias of the table used within the benchmark.
        :param data: Dictionary containing the data to write.
        :param primary_key: Tuple of (key_name, key_value) for the primary key.
        :param secondary_key: Optional tuple for the secondary/sort key.
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
        """
        Create a DynamoDB table for a benchmark.

        Generates a unique table name using resource ID, benchmark name, and provided name.
        Handles cases where the table already exists or is being created.
        Uses PAY_PER_REQUEST billing mode.

        In contrast to the hierarchy of database objects in Azure (account -> database -> container)
        and GCP (database per benchmark), we need to create unique table names here.

        :param benchmark: Name of the benchmark.
        :param name: Alias for the table within the benchmark.
        :param primary_key: Name of the primary key attribute.
        :param secondary_key: Optional name of the secondary/sort key attribute.
        :return: Actual name of the created or existing DynamoDB table.
        :raises RuntimeError: If table creation fails for an unknown reason.
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
        """
        Clear all items from a DynamoDB table.

        Note: This method is not implemented.

        :param name: Name of the table to clear.
        :raises NotImplementedError: This method is not yet implemented.
        """
        raise NotImplementedError()

    def remove_table(self, name: str) -> str:
        """
        Remove a DynamoDB table.

        Note: This method is not implemented.

        :param name: Name of the table to remove.
        :raises NotImplementedError: This method is not yet implemented.
        """
        raise NotImplementedError()
