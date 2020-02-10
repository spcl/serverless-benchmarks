
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
        name, extension = name.split('.')
        return '{name}.{random}.{extension}'.format(
                    name=name,
                    extension=extension,
                    random=str(uuid.uuid4()).split('-')[0]
                )

    def upload(self, container, file, filepath):
        with open(filepath, 'rb') as data:
            self.upload_stream(container, storage.unique_name(file), data)

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
    
    # it seems that JS does not have an API that would allow to 
    # upload/download data without going through container client
    def upload_stream(self, container, file, data):
        client = self.client.get_blob_client(
                container=container,
                blob=storage.unique_name(file)
        )
        return client.upload_blob(data)

    def download_stream(self, container, file):
        client = self.client.get_blob_client(container=container, blob=file)
        return client.download_blob().readall()
    
    def get_instance():
        if storage.instance is None:
            storage.instance = storage()
        return storage.instance
