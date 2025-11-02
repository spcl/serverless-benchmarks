from typing import List, Optional, Tuple


class nosql:

    instance: Optional["nosql"] = None

    @staticmethod
    def init_instance(entry: WorkerEntryPoint):
        nosql.instance = nosql()
        nosql.instance.env = entry.env

    def insert(
        self,
        table_name: str,
        primary_key: Tuple[str, str],
        secondary_key: Tuple[str, str],
        data: dict,
    ):
        put_res = await self.env.getattr(table_name).put(primary_key, data)
        return

    def update(
        self,
        table_name: str,
        primary_key: Tuple[str, str],
        secondary_key: Tuple[str, str],
        data: dict,
    ):
        await self.env.getattr(table_name).put(primary_key, data)
        return

    def get(
        self, table_name: str, primary_key: Tuple[str, str], secondary_key: Tuple[str, str]
    ) -> Optional[dict]:
        get_res = await self.env.getattr(table_name).get(primary_key)
        return get_res.json()

    """
        This query must involve partition key - it does not scan across partitions.
    """

    def query(
        self, table_name: str, primary_key: Tuple[str, str], secondary_key_name: str
    ) -> List[dict]:
        list_res = await self.env.getattr(table_name).list()

        return

    def delete(self, table_name: str, primary_key: Tuple[str, str], secondary_key: Tuple[str, str]):
        self.env.getattr(table_name).delete(primary_key)

        return

    @staticmethod
    def get_instance():
        if nosql.instance is None:
            nosql.instance = nosql()
        return nosql.instance
