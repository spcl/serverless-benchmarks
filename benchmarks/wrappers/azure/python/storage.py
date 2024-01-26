
import os
import uuid

from azure.storage.blob import BlobServiceClient


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
        self.client = BlobServiceClient.from_connection_string(
                os.getenv('STORAGE_CONNECTION_STRING')
            )

    @staticmethod
    def unique_name(name):
        name, extension = os.path.splitext(name)
        return '{name}.{random}.{extension}'.format(
                    name=name,
                    extension=extension,
                    random=str(uuid.uuid4()).split('-')[0]
                )

    def upload(self, container, file, filepath, unique_name=True):
        incr_io_env_file(filepath, "STORAGE_UPLOAD_BYTES")
        with open(filepath, 'rb') as data:
            return self.upload_stream(container, file, data, unique_name=unique_name)

    def download(self, container, file, filepath):
        with open(filepath, 'wb') as download_file:
            download_file.write( self.download_stream(container, file) )
        incr_io_env_file(filepath, "STORAGE_DOWNLOAD_BYTES")

    def download_directory(self, container, prefix, path):
        client = self.client.get_container_client(container=container)
        objects = client.list_blobs(name_starts_with=prefix)
        for obj in objects:
            file_name = obj.name
            path_to_file = os.path.dirname(file_name)
            os.makedirs(os.path.join(path, path_to_file), exist_ok=True)
            self.download(container, file_name, os.path.join(path, file_name))
            incr_io_env_file(os.path.join(path, file_name), "STORAGE_DOWNLOAD_BYTES")

    def upload_stream(self, container, file, data, unique_name=True):
        size = data.seek(0, 2)
        incr_io_env(size, "STORAGE_UPLOAD_BYTES")
        data.seek(0)
        key_name = storage.unique_name(file) if unique_name else file
        client = self.client.get_blob_client(
                container=container,
                blob=key_name
        )
        overwrite = not unique_name
        client.upload_blob(data, overwrite=overwrite)
        return key_name

    def download_stream(self, container, file):
        client = self.client.get_blob_client(container=container, blob=file)
        data = client.download_blob().readall()
        incr_io_env(len(data), "STORAGE_DOWNLOAD_BYTES")

        return data

    def download_within_range(self, container, file, start_byte, stop_byte):
        client = self.client.get_blob_client(container=container, blob=file)
        data = client.download_blob(offset=start_byte, length=(stop_byte-start_byte), encoding='UTF-8').readall()
        incr_io_env(len(data), "STORAGE_DOWNLOAD_BYTES")

        return data #.decode('utf-8')

    def list_directory(self, container, prefix):
        client = self.client.get_container_client(container=container)
        objects = client.list_blobs(name_starts_with=prefix)
        for obj in objects:
            yield obj.name

    def get_instance():
        if storage.instance is None:
            storage.instance = storage()
        return storage.instance
