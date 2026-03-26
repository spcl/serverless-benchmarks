from typing import List, Optional, Tuple
import json
import pickle
from pyodide.ffi import to_js, run_sync
from workers import WorkerEntrypoint, DurableObject


class nosql_do:
    instance: Optional["nosql_do"] = None
    DO_BINDING_NAME = "DURABLE_STORE"

    @staticmethod
    def init_instance(entry: WorkerEntrypoint):
        nosql_do.instance = nosql_do()
        nosql_do.instance.binding = getattr(entry.env, nosql_do.DO_BINDING_NAME)

    
    def get_table(self, table_name):
        kvapiobj = self.binding.getByName(table_name)
        return kvapiobj

    def key_maker(self, key1, key2):
            return f"({key1[0]},{str(key1[1])})+({key2[0]},{key2[1]})"
    
    def key_maker_partial(self, key1, key2):
        return f"({key1[0]},{str(key1[1])})+({key2[0]}"

## these data conversion funcs should not be necessary. i couldn't get pyodide to clone the data otherwise
    def data_pre(self, data):
        return pickle.dumps(data, 0).decode("ascii")

    def data_post(self, data):
        # Handle None (key not found in storage)
        if data is None:
            return None
        # Handle both string and bytes data from Durable Object storage
        if isinstance(data, str):
            return pickle.loads(bytes(data, "ascii"))
        else:
            return pickle.loads(data)
    
    def insert(
        self,
        table_name: str,
        primary_key: Tuple[str, str],
        secondary_key: Tuple[str, str],
        data: dict,
    ):
        send_data = self.data_pre(data)
        k=self.key_maker(primary_key, secondary_key)
        put_res = run_sync(self.get_table(table_name).put(k, send_data))
        return

    ## does this really need different behaviour from insert?
    def update(
        self,
        table_name: str,
        primary_key: Tuple[str, str],
        secondary_key: Tuple[str, str],
        data: dict,
    ):
        self.insert(table_name, primary_key, secondary_key, data)
        return 


    def get(
        self, table_name: str, primary_key: Tuple[str, str], secondary_key: Tuple[str, str]
    ) -> Optional[dict]:
        k=self.key_maker(primary_key, secondary_key)
        get_res = run_sync(self.get_table(table_name).get(k))
        ## print(get_res)
        return self.data_post(get_res)

    """
        This query must involve partition key - it does not scan across partitions.
    """

    def query(
        self, table_name: str, primary_key: Tuple[str, str], secondary_key_name: str
    ) -> List[dict]:

        prefix_key = self.key_maker_partial(primary_key, (secondary_key_name,))
        list_res = run_sync(self.get_table(table_name).list())
        
        keys = []
        for key in list_res:
            if key.startswith(prefix_key):
                print(key)
                keys.append(key)
        ##print("keys", keys)
        assert len(keys) <= 100


        # todo: please use bulk sometime (it didn't work when i tried it)
        res = []
        for key in keys:
            
            get_res = run_sync(self.get_table(table_name).get(key))
            ## print(get_res)
            res.append(self.data_post(get_res))
        return res

    def delete(self, table_name: str, primary_key: Tuple[str, str], secondary_key: Tuple[str, str]):
        run_sync(self.get_table(table_name).delete(self.key_maker(primary_key, secondary_key)))
        return

    @staticmethod
    def get_instance():
        if nosql_do.instance is None:
            nosql_do.instance = nosql_do()
        return nosql_do.instance

### ------------------------------

class nosql_kv:

    instance: Optional["nosql_kv"] = None

    @staticmethod
    def init_instance(entry: WorkerEntrypoint):
        nosql_kv.instance = nosql_kv()
        nosql_kv.instance.env = entry.env

    def key_maker(self, key1, key2):
        return f"{key1[1]}#{key2[1]}"

    def key_maker_partial(self, key1, key2):
        return f"{key1[1]}#"

    def index_key(self, primary_key):
        return f"__sebs_idx__{primary_key[1]}"

    def get_table(self, table_name):
        return getattr(self.env, (table_name))

    def insert(
        self,
        table_name: str,
        primary_key: Tuple[str, str],
        secondary_key: Tuple[str, str],
        data: dict,
    ):
        key_data = {**data}
        key_data[primary_key[0]] = primary_key[1]
        key_data[secondary_key[0]] = secondary_key[1]
        put_res = run_sync(
            self.get_table(table_name).put(
                self.key_maker(primary_key, secondary_key),
                json.dumps(key_data),
            )
        )

        idx_raw = run_sync(self.get_table(table_name).get(self.index_key(primary_key)))
        idx = []
        if idx_raw:
            idx = json.loads(idx_raw)
        if secondary_key[1] not in idx:
            idx.append(secondary_key[1])
            run_sync(self.get_table(table_name).put(self.index_key(primary_key), json.dumps(idx)))
        return

    def update(
        self,
        table_name: str,
        primary_key: Tuple[str, str],
        secondary_key: Tuple[str, str],
        data: dict,
    ):
        existing = self.get(table_name, primary_key, secondary_key)
        if existing is None:
            existing = {}
        merged = {**existing, **data}
        merged[primary_key[0]] = primary_key[1]
        merged[secondary_key[0]] = secondary_key[1]
        put_res = run_sync(
            self.get_table(table_name).put(
                self.key_maker(primary_key, secondary_key),
                json.dumps(merged),
            )
        )
        return

    def get(
        self, table_name: str, primary_key: Tuple[str, str], secondary_key: Tuple[str, str]
    ) -> Optional[dict]:
        get_res = run_sync(
            self.get_table(table_name).get(
                self.key_maker(primary_key, secondary_key)
            ))
        if get_res is None:
            return None
        if isinstance(get_res, dict):
            return get_res
        return json.loads(get_res)

    """
        This query must involve partition key - it does not scan across partitions.
    """

    def query(
        self, table_name: str, primary_key: Tuple[str, str], secondary_key_name: str
    ) -> List[dict]:
        idx_raw = run_sync(self.get_table(table_name).get(self.index_key(primary_key)))
        idx = []
        if idx_raw:
            idx = json.loads(idx_raw)

        res = []
        for secondary_key_value in idx:
            key = f"{primary_key[1]}#{secondary_key_value}"
            get_res = run_sync(self.get_table(table_name).get(key))
            if get_res is None:
                continue
            if isinstance(get_res, dict):
                res.append(get_res)
            else:
                res.append(json.loads(get_res))
        return res

    def delete(self, table_name: str, primary_key: Tuple[str, str], secondary_key: Tuple[str, str]):
        run_sync(self.get_table(table_name).delete(self.key_maker(primary_key, secondary_key)))

        idx_raw = run_sync(self.get_table(table_name).get(self.index_key(primary_key)))
        idx = []
        if idx_raw:
            idx = json.loads(idx_raw)
        if secondary_key[1] in idx:
            idx = [v for v in idx if v != secondary_key[1]]
            run_sync(self.get_table(table_name).put(self.index_key(primary_key), json.dumps(idx)))

        return

    @staticmethod
    def get_instance():
        if nosql_kv.instance is None:
            nosql_kv.instance = nosql_kv()
        return nosql_kv.instance




nosql = nosql_kv
