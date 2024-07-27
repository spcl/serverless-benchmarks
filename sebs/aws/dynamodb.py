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

    """
        AWS: create a DynamoDB Table
    """

    def create_table(self, benchmark: str, name: str, primary_key: str) -> str:

        try:
            ret = self.client.create_table(
                TableName=name,
                BillingMode="PAY_PER_REQUEST",
                AttributeDefinitions=[{"AttributeName": primary_key, "AttributeType": "S"}],
                KeySchema=[{"AttributeName": primary_key, "KeyType": "HASH"}],
            )

            if ret["TableDescription"]["TableStatus"] == "CREATING":

                self.logging.info(f"Waiting for creation of DynamoDB table {name}")
                waiter = self.client.get_waiter("table_exists")
                waiter.wait(TableName=name)

            self.logging.info(f"Created DynamoDB table {name} for benchmark {benchmark}")

            return ret["TableDescription"]["TableName"]

        except self.client.exceptions.ResourceInUseException as e:

            if "already exists" in e.response["Error"]["Message"]:
                return name

            raise RuntimeError(f"Creating DynamoDB failed, unknown reason! Error: {e}")

    def clear_table(self, name: str) -> str:
        raise NotImplementedError()

    def remove_table(self, name: str) -> str:
        raise NotImplementedError()
