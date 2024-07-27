from typing import List, Tuple

from azure.cosmos import CosmosClient

class nosql:
    instance = None
    client = None

    def __init__(self, url: str, credential: str, database: str):
        self._client = CosmosClient(
            url=url,
            credential=credential
        )
        self._db_client = self._client.get_database_client(database)
        self._containers = {}

    def get_table(self, table_name: str):

        if table_name not in self._containers:
            self._containers[table_name] = self._db_client.get_container_client(table_name)

        return self._containers[table_name]

    def insert(
        self,
        table_name: str,
        primary_key: Tuple[str, str],
        secondary_key: Tuple[str, str],
        data: dict
    ):

        for key in (primary_key, secondary_key):
            data[key[0]] = key[1]

        self.get_table(table_name).create_item(data)

    def get(
        self,
        table_name: str,
        primary_key: Tuple[str, str],
        secondary_key: Tuple[str, str]
    ) -> dict:
        return self.get_table(table_name).read_item(
            item=secondary_key[1],
            partition_key=primary_key[1]
        )

    """
        This query must involve partition key - it does not scan across partitions.
    """

    def query(self, table_name: str, primary_key: Tuple[str, str]) -> List[dict]:

        return list(self.get_table(table_name).query_items(
            f"SELECT * FROM c WHERE c.{primary_key[0]} = '{primary_key[1]}'",
            enable_cross_partition_query=False
        ))

    def delete(
        self,
        table_name: str,
        primary_key: Tuple[str, str],
        secondary_key: Tuple[str, str]
    ):

        self.get_table(table_name).delete_item(
            item=secondary_key[1],
            partition_key=primary_key[1]
        )

    @staticmethod
    def get_instance(url: str = None, credential: str = None, database: str = None):
        if nosql.instance is None:
            nosql.instance = nosql(url, credential, database)
        return nosql.instance
