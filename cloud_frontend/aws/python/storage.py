import io

import boto3


class storage:
    instance = None
    client = None

    def __init__(self):
        self.client = boto3.client('s3')
    
    def upload(self, bucket, file, filepath):
        self.client.upload_file(filepath, bucket, file)
    
    def download(self, bucket, file, filepath):
        self.client.download_file(bucket, file, filepath)

    def upload_stream(self, bucket, file, data):
        self.client.upload_fileobj(data, bucket, file)

    def download_stream(self, bucket, file):
        data = io.BytesIO()
        self.client.download_fileobj(bucket, file, data)
        return data.getbuffer()
    
    def get_instance():
        if storage.instance is None:
            storage.instance = storage()
        return storage.instance
