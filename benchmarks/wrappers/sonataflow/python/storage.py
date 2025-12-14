import os
import uuid

import minio


class storage:
    instance = None
    client = None

    def __init__(self):
        if "MINIO_ADDRESS" in os.environ:
            address = os.environ["MINIO_ADDRESS"]
            access_key = os.environ["MINIO_ACCESS_KEY"]
            secret_key = os.environ["MINIO_SECRET_KEY"]
            self.client = minio.Minio(
                address, access_key=access_key, secret_key=secret_key, secure=False
            )

    @staticmethod
    def unique_name(name):
        name, extension = os.path.splitext(name)
        return "{name}.{random}{extension}".format(
            name=name, extension=extension, random=str(uuid.uuid4()).split("-")[0]
        )

    def upload(self, bucket, file, filepath, unique_name=True):
        key_name = storage.unique_name(file) if unique_name else file
        self.client.fput_object(bucket, key_name, filepath)
        return key_name

    def download(self, bucket, file, filepath):
        data = self.client.get_object(bucket, file)
        size = data.headers.get("Content-Length")
        if size:
            os.environ["STORAGE_DOWNLOAD_BYTES"] = str(
                int(os.getenv("STORAGE_DOWNLOAD_BYTES", "0")) + int(size)
            )
        self.client.fget_object(bucket, file, filepath)

    def download_directory(self, bucket, prefix, path):
        objects = self.client.list_objects_v2(bucket, prefix, recursive=True)
        for obj in objects:
            file_name = obj.object_name
            self.download(bucket, file_name, os.path.join(path, file_name))

    def upload_stream(self, bucket, file, bytes_data):
        key_name = storage.unique_name(file)
        self.client.put_object(bucket, key_name, bytes_data, bytes_data.getbuffer().nbytes)
        return key_name

    def download_stream(self, bucket, file):
        data = self.client.get_object(bucket, file)
        body = data.read()
        os.environ["STORAGE_DOWNLOAD_BYTES"] = str(
            int(os.getenv("STORAGE_DOWNLOAD_BYTES", "0")) + len(body)
        )
        return body

    def download_within_range(self, bucket, file, start_byte, stop_byte):
        range_header = f"bytes={start_byte}-{stop_byte}"
        resp = self.client.get_object(bucket, file, request_headers={"Range": range_header})
        data = resp.read().decode("utf-8")
        os.environ["STORAGE_DOWNLOAD_BYTES"] = str(
            int(os.getenv("STORAGE_DOWNLOAD_BYTES", "0")) + len(data.encode("utf-8"))
        )
        return data

    def list_directory(self, bucket, prefix):
        if hasattr(self.client, "list_objects_v2"):
            iterator = self.client.list_objects_v2(bucket, prefix, recursive=True)
        else:
            iterator = self.client.list_objects(bucket, prefix, recursive=True)
        for obj in iterator:
            yield obj.object_name

    def get_instance():
        if storage.instance is None:
            storage.instance = storage()
        return storage.instance
