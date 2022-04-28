import os
import uuid
import json
import minio
import logging


class storage:
    instance = None
    client = None

    def __init__(self):
        try:
            self.client = minio.Minio(
                os.getenv("MINIO_STORAGE_CONNECTION_URL"),
                access_key=os.getenv("MINIO_STORAGE_ACCESS_KEY"),
                secret_key=os.getenv("MINIO_STORAGE_SECRET_KEY"),
                secure=False,
            )
        except Exception as e:
            logging.info(e)
            raise e

    @staticmethod
    def unique_name(name):
        name, extension = name.split(".")
        return "{name}.{random}.{extension}".format(
            name=name, extension=extension, random=str(uuid.uuid4()).split("-")[0]
        )

    def upload(self, bucket, file, filepath):
        key_name = storage.unique_name(file)
        self.client.fput_object(bucket, key_name, filepath)
        return key_name

    def download(self, bucket, file, filepath):
        self.client.fget_object(bucket, file, filepath)

    def download_directory(self, bucket, prefix, path):
        objects = self.client.list_objects(bucket, prefix, recursive=True)
        for obj in objects:
            file_name = obj.object_name
            self.download(bucket, file_name, os.path.join(path, file_name))

    def upload_stream(self, bucket, file, bytes_data):
        key_name = storage.unique_name(file)
        self.client.put_object(
            bucket, key_name, bytes_data, bytes_data.getbuffer().nbytes
        )
        return key_name

    def download_stream(self, bucket, file):
        data = self.client.get_object(bucket, file)
        return data.read()

    @staticmethod
    def get_instance():
        if storage.instance is None:
            storage.instance = storage()
        return storage.instance
