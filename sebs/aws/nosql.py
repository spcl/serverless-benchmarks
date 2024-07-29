
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
        benchmark: str,
        session: boto3.session.Session,
        cache_client: Cache,
        resources: Resources,
        region: str
    ):
        super().__init__(benchmark, region, cache_client, resources)
        self.client = session.client(
            "dynamodb",
            region_name=region
        )

    # TODO: "table names must be unique within each Region" - either take
    # care of this here or the caller will have to do it. If we do it here,
    # we can use the value stored for the self.benchmark member
    def create_table(self, table_name: str, primary_key: str):
        try:
            self.logging.info("Creating DynamoDB table {}".format(table_name))

            ret = self.client.create_table(
                AttributeDefinitions=[
                    {
                        "AttributeName": primary_key,
                        "AttributeType": "S"
                    }
                ],
                KeySchema=[
                    {
                        "AttributeName": primary_key,
                        "KeyType": "HASH"
                    }
                ],
                TableName=table_name,
                BillingMode="PAY_PER_REQUEST"
            )

            if (ret["TableDescription"]["TableStatus"]) == "CREATING":
                self.logging.info(f"Waiting for DynamoDB table creation to finish...")

                waiter = self.client.get_waiter("table_exists")
                waiter.wait(TableName=table_name, WaiterConfig={ "Delay": 5 })

            self.tables[table_name] = primary_key
            self.logging.info("Created DynamoDB table {}".format(table_name))
        except self.client.exceptions.ResourceInUseException as err:
            if ("Table already exists" in err.response["Error"]["Message"]):
                self.tables[table_name] = primary_key
                self.logging.info("Reusing existing DynamoDB table {}".format(table_name))
                return

            raise RuntimeError("Failed to create DynamoDB table: {}".format(err))

    # Following the delete-and-recreate proposed solution
    def clear_table(self, table_name: str) -> str:
        self.logging.info("Clearing DynamoDB table {}".format(table_name))

        primary_key = self.tables[table_name] # Need to save it
        self.remove_table(table_name)
        self.create_table(table_name, primary_key)

    def remove_table(self, table_name: str) -> str:
        self.logging.info("Removing DynamoDB table {}".format(table_name))

        self.client.delete_table(TableName=table_name)

        waiter = self.client.get_waiter("table_not_exists")
        waiter.wait(TableName=table_name, WaiterConfig={ "Delay": 5 })

        del self.tables[table_name]

        self.logging.info("Removed DynamoDB table {}".format(table_name))