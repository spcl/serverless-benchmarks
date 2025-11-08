import io
import os
import uuid

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
    handle = None

    @staticmethod
    def unique_name(name):
        name, extension = os.path.splitext(name)
        return '{name}.{random}{extension}'.format(
                    name=name,
                    extension=extension,
                    random=str(uuid.uuid4()).split('-')[0]
                )

    @staticmethod
    def init_instance(entry: WorkerEntrypoint):
        storage.instance = storage()
        storage.instance.handle = entry.env.R2
        storage.instance.written_files = set()

    def upload(self, __bucket, key, filepath):
        if filepath in self.written_files:
            filepath = "/tmp" + os.path.abspath(filepath)
        with open(filepath, "rb") as f:
            self.upload_stream(__bucket, key, f.read())
        return

    def download(self, __bucket, key, filepath):
        data = self.download_stream(__bucket, key)
        # should only allow writes to tmp dir. so do have to edit the filepath here?
        tmp_fp = "/tmp" + os.path.abspath(filepath)
        self.written_files.append(filepath)
        with open(tmp_fp, "wb") as f:
            f.write(data)
        return

    def download_directory(self, __bucket, prefix, out_path):
        print(self.handle, type(self.handle))
        list_res = self.handle.list(prefix = prefix) ## gives only first 1000?
        for obj in list_res.objects:
            file_name = obj.key
            path_to_file = os.path.dirname(file_name)
            os.makedirs(os.path.join(path, path_to_file), exist_ok=True)
            self.download(__bucket, file_name, os.path.join(out_path, file_name))
        return

    def upload_stream(self, __bucket, key, data):
        unique_key = storage.unique_name(key)
        put_res = self.handle.put(unique_key, data)
        return unique_key

    def download_stream(self, __bucket, key):
        get_res = self.handle.get(key)
        assert get_res is not None
        data = get_res.text()
        return data

    def get_instance():
        if storage.instance is None:
            raise "must init storage singleton first"
        return storage.instance
