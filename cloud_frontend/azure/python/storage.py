
import os

from azure.storage.blob import BlobServiceClient


class storage:
    instance = None
    client = None

    def __init__(self):
        self.client = BlobServiceClient.from_connection_string(
                os.getenv('STORAGE_CONNECTION_STRING')
            )
    
    # it seems that JS does not have an API that would allow to 
    # upload/download data without going through container client
    def upload_stream(self, container, file, data):
        let container_client = self.client.getContainerClient(container);
        client = self.client.get_blob_client(container=container, blob=file)
        return client.upload_blob(data)

    def download_stream(self, container, file):
        client = self.client.get_blob_client(container=container, blob=file)
        return client.download_blob().readall()
    
    def get_instance():
        if storage.instance is None:
            storage.instance = storage()
        return storage.instance
