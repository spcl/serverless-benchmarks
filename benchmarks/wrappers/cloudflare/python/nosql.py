from typing import List, Optional, Tuple
import json
from pyodide.ffi import to_js
from workers import WorkerEntrypoint

class nosql:

    instance: Optional["nosql"] = None

    @staticmethod
    def init_instance(entry: WorkerEntrypoint):
        nosql.instance = nosql()
        nosql.instance.env = entry.env

    def key_maker(self, key1, key2):
        return f"({key1[0]},{str(key1[1])})+({key2[0]},{key2[1]})"

    def key_maker_partial(self, key1, key2):
        return f"({key1[0]},{str(key1[1])})+({key2[0]}"

    def get_table(self, table_name):
        return getattr(self.env, (table_name))

    async def insert(
        self,
        table_name: str,
        primary_key: Tuple[str, str],
        secondary_key: Tuple[str, str],
        data: dict,
    ):
        put_res = await self.get_table(table_name).put(
            self.key_maker(primary_key, secondary_key),
            json.dumps(data))
        return

    async def update(
        self,
        table_name: str,
        primary_key: Tuple[str, str],
        secondary_key: Tuple[str, str],
        data: dict,
    ):
        put_res = await self.get_table(table_name).put(
            self.key_maker(primary_key, secondary_key),
            data)
        return

    async def get(
        self, table_name: str, primary_key: Tuple[str, str], secondary_key: Tuple[str, str]
    ) -> Optional[dict]:
        get_res = await self.get_table(table_name).get(self.key_maker(primary_key, secondary_key))
        return get_res

    """
        This query must involve partition key - it does not scan across partitions.
    """

    async def query(
        self, table_name: str, primary_key: Tuple[str, str], secondary_key_name: str
    ) -> List[dict]:
        _options = {"prefix" : self.key_maker_partial(primary_key, (secondary_key_name,) )}
        list_res = await self.get_table(table_name).list(options=_options)

        keys = []
        for key in list_res.keys:
            keys.append(key.name)
        print("keys", keys)
        assert len(keys) <= 100


        # todo: please use bulk sometime (it didn't work when i tried it)
        res = []
        for key in keys:
            
            get_res = await self.get_table(table_name).get(key)
            get_res = get_res.replace("\'", "\"")
            print("gr", get_res)
        
            res.append(json.loads(get_res))
        return res

    async def delete(self, table_name: str, primary_key: Tuple[str, str], secondary_key: Tuple[str, str]):
        self.get_table(table_name).delete(self.key_maker(primary_key, secondary_key))

        return

    @staticmethod
    def get_instance():
        if nosql.instance is None:
            nosql.instance = nosql()
        return nosql.instance
