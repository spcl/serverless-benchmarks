from typing import Optional

from sebs.cache import Cache
from sebs.faas.config import Resources
from sebs.faas.nosql import NoSQLStorage

import boto3


class DynamoDB(NoSQLStorage):
    @staticmethod
    def typename() -> str:
        return "AWS.DynamoDB"

    @staticmethod
    def deployment_name():
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
        super().__init__(region, cache_client, resources)
        self.client = session.client(
            "dynamodb",
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    def retrieve_cache(self, benchmark: str) -> bool:

        if benchmark in self._tables:
            return True

        cached_storage = self.cache_client.get_nosql_config(self.deployment_name(), benchmark)
        if cached_storage is not None:
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
        AWS: create a DynamoDB Table
    """

    def create_table(
        self, benchmark: str, name: str, primary_key: str, secondary_key: Optional[str] = None
    ) -> str:

        try:

            definitions = [{"AttributeName": primary_key, "AttributeType": "S"}]
            key_schema = [{"AttributeName": primary_key, "KeyType": "HASH"}]

            if secondary_key is not None:
                definitions.append({"AttributeName": secondary_key, "AttributeType": "S"})
                key_schema.append({"AttributeName": secondary_key, "KeyType": "RANGE"})

            ret = self.client.create_table(
                TableName=name,
                BillingMode="PAY_PER_REQUEST",
                AttributeDefinitions=definitions,
                KeySchema=key_schema,
            )

            if ret["TableDescription"]["TableStatus"] == "CREATING":

                self.logging.info(f"Waiting for creation of DynamoDB table {name}")
                waiter = self.client.get_waiter("table_exists")
                waiter.wait(TableName=name)

            self.logging.info(f"Created DynamoDB table {name} for benchmark {benchmark}")

            return ret["TableDescription"]["TableName"]

        except self.client.exceptions.ResourceInUseException as e:

            if "already exists" in e.response["Error"]["Message"]:
                self.logging.info(f"Using existing DynamoDB table {name} for benchmark {benchmark}")
                return name

            raise RuntimeError(f"Creating DynamoDB failed, unknown reason! Error: {e}")

    def clear_table(self, name: str) -> str:
        raise NotImplementedError()

    def remove_table(self, name: str) -> str:
        raise NotImplementedError()
