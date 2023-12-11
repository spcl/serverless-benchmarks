import io
import os
import uuid

import boto3


def incr_io_env_file(filepath, key):
    stats = os.stat(filepath)
    incr_io_env(stats.st_size, key)


def incr_io_env(val, key):
    cnt = int(os.getenv(key, "0"))
    os.environ[key] = str(cnt + val)


class storage:
    instance = None
    client = None

    def __init__(self):
        self.client = boto3.client('s3')

    @staticmethod
    def unique_name(name):
        name, extension = os.path.splitext(name)
        return '{name}.{random}{extension}'.format(
                    name=name,
                    extension=extension,
                    random=str(uuid.uuid4()).split('-')[0]
                )

    def upload(self, bucket, file, filepath, unique_name=True):
        incr_io_env_file(filepath, "STORAGE_UPLOAD_BYTES")

        key_name = storage.unique_name(file) if unique_name else file
        self.client.upload_file(filepath, bucket, key_name)
        return key_name

    def download(self, bucket, file, filepath):
        self.client.download_file(bucket, file, filepath)
        incr_io_env_file(filepath, "STORAGE_DOWNLOAD_BYTES")

    def download_directory(self, bucket, prefix, path):
        objects = self.client.list_objects_v2(Bucket=bucket, Prefix=prefix)
        for obj in objects['Contents']:
            file_name = obj['Key']
            path_to_file = os.path.dirname(file_name)
            os.makedirs(os.path.join(path, path_to_file), exist_ok=True)
            self.download(bucket, file_name, os.path.join(path, file_name))
            incr_io_env_file(os.path.join(path, file_name), "STORAGE_DOWNLOAD_BYTES")

    def upload_stream(self, bucket, file, data):
        size = data.seek(0, 2)
        incr_io_env(size, "STORAGE_UPLOAD_BYTES")
        data.seek(0)
        key_name = storage.unique_name(file)
        self.client.upload_fileobj(data, bucket, key_name)
        return key_name

    def download_stream(self, bucket, file):
        data = io.BytesIO()
        self.client.download_fileobj(bucket, file, data)
        incr_io_env(data.tell(), "STORAGE_DOWNLOAD_BYTES")
        return data.getbuffer()
    
    def download_within_range(self, bucket, file, start_byte, stop_byte):
        resp = self.client.get_object(Bucket=bucket, Key=file, Range='bytes={}-{}'.format(start_byte, stop_byte))
        return resp['Body'].read().decode('utf-8')

    def list_directory(self, bucket, prefix):
        objects = self.client.list_objects_v2(Bucket=bucket, Prefix=prefix)
        for obj in objects['Contents']:
            yield obj['Key']

    def get_instance():
        if storage.instance is None:
            storage.instance = storage()
        return storage.instance
