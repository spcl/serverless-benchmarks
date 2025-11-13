import io
import os
import uuid
import asyncio
from pyodide.ffi import to_js, jsnull
from pyodide.webloop import WebLoop

from workers import WorkerEntrypoint

## all filesystem calls will rely on the node:fs flag
""" layout
/bundle
└── (one file for each module in your Worker bundle)
/tmp
└── (empty, but you can write files, create directories, symlinks, etc)
/dev
├── null
├── random
├── full
└── zero
"""
class storage:
    instance = None

    @staticmethod
    def unique_name(name):
        name, extension = os.path.splitext(name)
        return '{name}.{random}{extension}'.format(
                    name=name,
                    extension=extension,
                    random=str(uuid.uuid4()).split('-')[0]
                )
    def get_bucket(self, bucket):
        return getattr(self.entry_env, bucket)

    @staticmethod
    def init_instance(entry: WorkerEntrypoint):
        storage.instance = storage()
        storage.instance.entry_env = entry.env
        storage.instance.written_files = set()
        ## should think of a way to del the runner at program end
        storage.instance.runner = asyncio.Runner(loop_factory=None)

    def upload(self, bucket, key, filepath):
        if filepath in self.written_files:
            filepath = "/tmp" + os.path.abspath(filepath)
        with open(filepath, "rb") as f:
            unique_key = self.upload_stream(bucket, key, f.read())
        return unique_key

    def download(self, bucket, key, filepath):
        data = self.download_stream(bucket, key)
        # should only allow writes to tmp dir. so do have to edit the filepath here?
        real_fp = filepath
        if not filepath.startswith("/tmp"):
            real_fp = "/tmp" + os.path.abspath(filepath)

        self.written_files.append(filepath)
        with open(real_fp, "wb") as f:
            f.write(data)
        return

    def download_directory(self, bucket, prefix, out_path):
        bobj = self.get_bucket(bucket)
        list_res = self.runner,run(bobj.list(prefix = prefix)) ## gives only first 1000?
        for obj in list_res.objects:
            file_name = obj.key
            path_to_file = os.path.dirname(file_name)
            os.makedirs(os.path.join(path, path_to_file), exist_ok=True)
            self.download(bucket, file_name, os.path.join(out_path, file_name))
        return

    def upload_stream(self, bucket, key, data):
        return self.runner.run(selfaupload_stream(bucket, key, data))

    async def aupload_stream(self, bucket, key, data):
        unique_key = storage.unique_name(key)
        data_js = to_js(data)
        bobj = self.get_bucket(bucket)
        put_res = await bobj.put(unique_key, data_js)
        ##print(put_res)
        return unique_key

    def download_stream(self, bucket, key):
        return self.runner.run(self.adownload_stream(bucket, key))

    async def adownload_stream(self, bucket, key):
        bobj = self.get_bucket(bucket)
        get_res = bobj.get(key)
        if get_res == jsnull:
            print("key not stored in bucket")
            return b''
        data = await get_res.text()
        return data

    def get_instance():
        if storage.instance is None:
            raise "must init storage singleton first"
        return storage.instance
