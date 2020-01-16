import io
import os
import minio

class storage:
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

    def upload_stream(self, bucket, file, bytes_data):
        self.client.put_object(bucket, file, bytes_data, bytes_data.getbuffer().nbytes)

    def download_stream(self, bucket, file):
        data = self.client.get_object(bucket, file)
        return data.read()

    def get_instance():
        if storage.instance is None:
            storage.instance = storage()
        return storage.instance

