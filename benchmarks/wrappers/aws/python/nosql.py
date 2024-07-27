from typing import List, Tuple

import boto3

class nosql:
    instance = None
    client = None

    def __init__(self):
        self.client = boto3.resource('dynamodb')
        self._tables = {}

    def get_table(self, table_name: str):

        if table_name not in self._tables:
            self._tables[table_name] = self.client.Table(table_name)

        return self._tables[table_name]

    def insert(
        self,
        table_name: str,
        primary_key: Tuple[str, str],
        secondary_key: Tuple[str, str],
        data: dict
    ):
        for key in (primary_key, secondary_key):
            data[key[0]] = key[1]

        self.get_table(table_name).put_item(
            TableName=table_name,
            Item=data
        )

    def get(
        self,
        table_name: str,
        primary_key: Tuple[str, str],
        secondary_key: Tuple[str, str]
    ) -> dict:

        data = {}
        for key in (primary_key, secondary_key):
            data[key[0]] = key[1]

        res = self.get_table(table_name).get_item(
            TableName=table_name,
            Key=data
        )
        return res['Item']

    def query(self, table_name: str, primary_key: Tuple[str, str]) -> List[dict]:

        return self.get_table(table_name).query(
            KeyConditionExpression=f"{primary_key[0]} = :keyvalue",
            ExpressionAttributeValues={
                ':keyvalue': primary_key[1]
            }
        )['Items']

    def delete(
        self,
        table_name: str,
        primary_key: Tuple[str, str],
        secondary_key: Tuple[str, str]
    ):
        data = {}
        for key in (primary_key, secondary_key):
            data[key[0]] = key[1]

        self.get_table(table_name).delete_item(
            TableName=table_name,
            Key=data
        )

    @staticmethod
    def get_instance():
        if nosql.instance is None:
            nosql.instance = nosql()
        return nosql.instance
