import os
import minio

class minio_wrapper:
    instance = None
    client = None

    def __init__(self):
        if 'MINIO_ADDRESS' in os.environ:
            address = os.environ['MINIO_ADDRESS']
            access_key = os.environ['MINIO_ACCESS_KEY']
            secret_key = os.environ['MINIO_SECRET_KEY']
            self.client = minio.Minio(
                    address,
                    access_key=access_key,
                    secret_key=secret_key,
                    secure=False)

    def upload(self, bucket, file, filepath):
        self.client.fput_object(bucket, file, filepath)
    
    def download(self, bucket, file, filepath):
        self.client.fget_object(bucket, file, filepath)

    def get_instance():
        if minio_wrapper.instance is None:
            minio_wrapper.instance = minio_wrapper()
        return minio_wrapper.instance

