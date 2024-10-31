import io
import os
import uuid

from google.cloud import storage as gcp_storage


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

    def upload(self, bucket, file, filepath, overwrite=False):
        key_name = storage.unique_name(file)
        if (overwrite):
            key_name = file
        bucket_instance = self.client.bucket(bucket)
        blob = bucket_instance.blob(key_name)
        blob.upload_from_filename(filepath)
        return key_name

    def download(self, bucket, file, filepath):
        bucket_instance = self.client.bucket(bucket)
        blob = bucket_instance.blob(file)
        blob.download_to_filename(filepath)

    def download_directory(self, bucket, prefix, path):
        objects = self.client.bucket(bucket).list_blobs(prefix=prefix)
        for obj in objects:
            file_name = obj.name
            path_to_file = os.path.dirname(file_name)
            os.makedirs(os.path.join(path, path_to_file), exist_ok=True)
            self.download(bucket, file_name, os.path.join(path, file_name))

    def upload_stream(self, bucket, file, data):
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
        return data.getbuffer()

    def get_object(self, bucket, key):
        bucket_instance = self.client.bucket(bucket)
        blob = bucket_instance.blob(key)
        contents = blob.download_as_bytes()
        return contents['Body'].read().decode('utf-8')

    def get_instance():
        if storage.instance is None:
            storage.instance = storage()
        return storage.instance

    def list_blobs(self, bucket):
        res = self.client.list_blobs(bucket)

        objs = []
        for obj in res:
            objs.append(obj.name)

        return objs
