
import os
import uuid

from azure.storage.blob import BlobServiceClient

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
        return '{name}.{random}{extension}'.format(
                    name=name,
                    extension=extension,
                    random=str(uuid.uuid4()).split('-')[0]
                )

    def upload(self, container, file, filepath, overwrite=False):
        with open(filepath, 'rb') as data:
            return self.upload_stream(container, file, data, overwrite)

    def download(self, container, file, filepath):
        with open(filepath, 'wb') as download_file:
            download_file.write( self.download_stream(container, file) )
    
    def download_directory(self, container, prefix, path):
        client = self.client.get_container_client(container=container)
        objects = client.list_blobs(name_starts_with=prefix)
        for obj in objects:
            file_name = obj.name
            path_to_file = os.path.dirname(file_name)
            os.makedirs(os.path.join(path, path_to_file), exist_ok=True)
            self.download(container, file_name, os.path.join(path, file_name))
    
    def upload_stream(self, container, file, data, overwrite=False):
        key_name = storage.unique_name(file)
        if (overwrite):
            key_name = file
        client = self.client.get_blob_client(
                container=container,
                blob=key_name
        )
        client.upload_blob(data, overwrite=overwrite)
        return key_name

    def download_stream(self, container, file):
        client = self.client.get_blob_client(container=container, blob=file)
        return client.download_blob().readall()
    
    def get_instance():
        if storage.instance is None:
            storage.instance = storage()
        return storage.instance

    def get_object(self, container, key):
        blob_client = self.client.get_blob_client(container=container, blob=key)
        downloader = blob_client.download_blob(max_concurrency=1, encoding='UTF-8')
        return downloader.readall()

    def list_blobs(self, container):
        client = self.client.get_container_client(container=container)

        # Azure returns an iterator. Turn it into a list.
        objs = []
        res = client.list_blob_names()
        for obj in res:
            objs.append(obj)

        return objs
