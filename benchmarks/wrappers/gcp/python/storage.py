import io
import os
import uuid

from google.cloud import storage as gcp_storage


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
        self.client = gcp_storage.Client()

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
        bucket_instance = self.client.bucket(bucket)
        blob = bucket_instance.blob(key_name)
        blob.upload_from_filename(filepath)
        return key_name

    def download(self, bucket, file, filepath):
        bucket_instance = self.client.bucket(bucket)
        blob = bucket_instance.blob(file)
        blob.download_to_filename(filepath)
        incr_io_env_file(filepath, "STORAGE_DOWNLOAD_BYTES")

    def download_directory(self, bucket, prefix, path):
        objects = self.client.bucket(bucket).list_blobs(prefix=prefix)
        for obj in objects:
            file_name = obj.name
            path_to_file = os.path.dirname(file_name)
            os.makedirs(os.path.join(path, path_to_file), exist_ok=True)
            self.download(bucket, file_name, os.path.join(path, file_name))
            incr_io_env_file(os.path.join(path, file_name), "STORAGE_DOWNLOAD_BYTES")

    def upload_stream(self, bucket, file, data):
        size = data.seek(0, 2)
        incr_io_env(size, "STORAGE_UPLOAD_BYTES")
        data.seek(0)
        key_name = storage.unique_name(file)
        bucket_instance = self.client.bucket(bucket)
        blob = bucket_instance.blob(key_name)
        blob.upload_from_file(data)
        return key_name

    def download_stream(self, bucket, file):
        data = io.BytesIO()
        bucket_instance = self.client.bucket(bucket)
        blob = bucket_instance.blob(file)
        blob.download_to_file(data)

        size = data.seek(0, 2)
        incr_io_env(size, "STORAGE_DOWNLOAD_BYTES")
        data.seek(0)

        return data

        return data.getbuffer()

    def download_within_range(self, bucket, file, start_byte, stop_byte):
        bucket_instance = self.client.bucket(bucket)
        blob = bucket_instance.blob(file)
        blob.download_to_filename('/tmp/' + file, start=start_byte, end=stop_byte)
        with open('/tmp/' + file, 'r') as f:
            content = f.read()
        return content

    def list_directory(self, bucket, prefix):
        objects = self.client.bucket(bucket).list_blobs(prefix=prefix)
        for obj in objects:
            yield obj.name

    def get_instance():
        if storage.instance is None:
            storage.instance = storage()
        return storage.instance
