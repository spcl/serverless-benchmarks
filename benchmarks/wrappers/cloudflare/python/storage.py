import io
import os
import uuid
import asyncio
import base64
from pyodide.ffi import to_js, jsnull, run_sync, JsProxy
from pyodide.webloop import WebLoop
import js

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
        # R2 buckets are always bound as 'R2' in wrangler.toml
        # The bucket parameter is the actual bucket name but we access via the binding
        return self.entry_env.R2

    @staticmethod
    def init_instance(entry: WorkerEntrypoint):
        storage.instance = storage()
        storage.instance.entry_env = entry.env
        storage.instance.written_files = set()
        
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

        self.written_files.add(filepath)
        with open(real_fp, "wb") as f:
            f.write(data)
        return

    def download_directory(self, bucket, prefix, out_path):
        bobj = self.get_bucket(bucket)
        list_res = run_sync(bobj.list(to_js({"prefix": prefix})))
        for obj in list_res.objects:
            file_name = obj.key
            path_to_file = os.path.dirname(file_name)
            os.makedirs(os.path.join(out_path, path_to_file), exist_ok=True)
            self.download(bucket, file_name, os.path.join(out_path, file_name))
        return

    def upload_stream(self, bucket, key, data):
        return run_sync(self.aupload_stream(bucket, key, data))

    async def aupload_stream(self, bucket, key, data):
        unique_key = storage.unique_name(key)
        # Handle BytesIO objects - extract bytes
        if hasattr(data, 'getvalue'):
            data = data.getvalue()
        # Convert bytes to Blob using base64 encoding as intermediate step
        if isinstance(data, bytes):
            # Encode as base64
            b64_str = base64.b64encode(data).decode('ascii')
            # Create a Response from base64, then get the blob
            # This creates a proper JavaScript Blob that R2 will accept
            response = await js.fetch(f"data:application/octet-stream;base64,{b64_str}")
            blob = await response.blob()
            data_js = blob
        else:
            data_js = str(data)
        bobj = self.get_bucket(bucket)
        put_res = await bobj.put(unique_key, data_js)
        return unique_key

    def download_stream(self, bucket, key):
        return run_sync(self.adownload_stream(bucket, key))

    async def adownload_stream(self, bucket, key):
        bobj = self.get_bucket(bucket)
        get_res = await bobj.get(key)
        if get_res == jsnull:
            print("key not stored in bucket")
            return b''
        # Always read as raw binary data (Blob/ArrayBuffer)
        data = await get_res.bytes()
        return bytes(data)

    @staticmethod
    def get_instance():
        if storage.instance is None:
            raise RuntimeError("must init storage singleton first")
        return storage.instance
        return storage.instance
