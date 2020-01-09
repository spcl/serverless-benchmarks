
import boto3


class storage:
    instance = None
    client = None

    def __init__(self):
        self.client = boto3.client('s3')
    
    def upload(self, bucket, file, filepath):
        #TODO
        self.client.put_object(Bucket=bucket, Key=file, Body=filepath)
    
    def download(self, bucket, file, filepath):
        #TODO
        self.client.get_object(Bucket=bucket, Key=file)
    
    def get_instance():
        if storage.instance is None:
            storage.instance = storage()
        return storage.instance
