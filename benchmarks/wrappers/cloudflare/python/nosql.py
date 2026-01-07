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

    def insert(
        self,
        table_name: str,
        primary_key: Tuple[str, str],
        secondary_key: Tuple[str, str],
        data: dict,
    ):
        put_res = (
            run_sync(self.get_table(table_name).put(
                self.key_maker(primary_key, secondary_key),
                json.dumps(data))
            ))
        return

    def update(
        self,
        table_name: str,
        primary_key: Tuple[str, str],
        secondary_key: Tuple[str, str],
        data: dict,
    ):
        put_res = run_sync(
            self.get_table(table_name).put(
                self.key_maker(primary_key, secondary_key),
                json.dumps(data)
            ))
        return

    def get(
        self, table_name: str, primary_key: Tuple[str, str], secondary_key: Tuple[str, str]
    ) -> Optional[dict]:
        get_res = run_sync(
            self.get_table(table_name).get(
                self.key_maker(primary_key, secondary_key)
            ))
        return get_res

    """
        This query must involve partition key - it does not scan across partitions.
    """

    def query(
        self, table_name: str, primary_key: Tuple[str, str], secondary_key_name: str
    ) -> List[dict]:
        _options = {"prefix" : self.key_maker_partial(primary_key, (secondary_key_name,) )}
        list_res = run_sync(self.get_table(table_name).list(options=_options))

        keys = []
        for key in list_res.keys:
            keys.append(key.name)
        ##print("keys", keys)
        assert len(keys) <= 100


        # todo: please use bulk sometime (it didn't work when i tried it)
        res = []
        for key in keys:
            
            get_res = run_sync(self.get_table(table_name).get(key))
            get_res = get_res.replace("\'", "\"")
            ##print("gr", get_res)
        
            res.append(json.loads(get_res))
        return res

    def delete(self, table_name: str, primary_key: Tuple[str, str], secondary_key: Tuple[str, str]):
        run_sync(self.get_table(table_name).delete(self.key_maker(primary_key, secondary_key)))

        return

    @staticmethod
    def get_instance():
        if nosql.instance is None:
            nosql.instance = nosql()
        return nosql.instance




nosql = nosql_do
