import io
import os

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

    def download_directory(self, bucket, prefix, path):
        objects = self.client.list_objects_v2(Bucket=bucket, Prefix=prefix)
        for obj in objects['Contents']:
            file_name = obj['Key']
            path_to_file = os.path.dirname(file_name)
            os.makedirs(os.path.join(path, path_to_file), exist_ok=True)
            self.download(bucket, file_name, os.path.join(path, file_name))

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
