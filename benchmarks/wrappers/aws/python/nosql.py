
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

    def insert(self, table_name: str, key: str, data: dict):
        self.get_table(table_name).put_item(
            TableName=table_name,
            Item=data
        )

    def get(self, table_name: str, key_name: str, key: str) -> dict:
        res = self.get_table(table_name).get_item(
            TableName=table_name,
            Key={
                key_name: key
            }
        )
        return res['Item']

    def delete(self, table_name: str, key_name: str, key: str):
        self.get_table(table_name).delete_item(
            TableName=table_name,
            Key={
                key_name: key
            }
        )

    @staticmethod
    def get_instance():
        if nosql.instance is None:
            nosql.instance = nosql()
        return nosql.instance
