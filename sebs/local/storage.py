import secrets
from typing import List

import docker
import minio

from sebs.cache import Cache
from ..faas.storage import PersistentStorage


class Minio(PersistentStorage):
    @staticmethod
    def typename() -> str:
        return "Local.Minio"

    @staticmethod
    def deployment_name():
        return "local"

    def __init__(self, docker_client: docker.client, cache_client: Cache, replace_existing: bool):
        super().__init__(cache_client, replace_existing)
        self._docker_client = docker_client
        self._port = 9000
        self._location = "us-east-1"
        self._storage_container: Optional[docker.container] = None

    def start(self):
        self._access_key = secrets.token_urlsafe(32)
        self._secret_key = secrets.token_hex(32)
        self.logging.info("Minio storage ACCESS_KEY={}".format(self._access_key))
        self.logging.info("Minio storage SECRET_KEY={}".format(self._secret_key))
        try:
            self._storage_container = self._docker_client.containers.run(
                "minio/minio",
                command="server /data",
                ports={
                    str(self._port): self._port
                },
                environment={
                    "MINIO_ACCESS_KEY": self._access_key,
                    "MINIO_SECRET_KEY": self._secret_key
                },
                remove=True,
                stdout=True,
                stderr=True,
                detach=True,
            )
            # who knows why? otherwise attributes are not loaded
            self._storage_container.reload()
            networks = self._storage_container.attrs["NetworkSettings"]["Networks"]
            self._url = "{IPAddress}:{Port}".format(
                IPAddress=networks["bridge"]["IPAddress"], Port=self._port
            )
            self.logging.info("Starting minio instance at {}".format(self._url))
            self.connection = self.get_connection()
        except docker.errors.APIError as e:
            self.logging.error("Starting Minio storage failed! Reason: {}".format(e))
            raise RuntimeError(f"Starting Minio storage unsuccesful")
        except Exception as e:
            self.logging.error("Starting Minio storage failed! Unknown error: {}".format(e))
            raise RuntimeError(f"Starting Minio storage unsuccesful")

    def stop(self):
        if self._storage_container is not None:
            self.logging.info("Stopping minio instance at {url}".format(url=self._url))
            self._storage_container.stop()

    def get_connection(self):
        return minio.Minio(
            self._url,
            access_key=self._access_key,
            secret_key=self._secret_key,
            secure=False
        )

    def config_to_json(self):
        if self._storage_container is not None:
            return {
                "address": self.url,
                "secret_key": self._secret_key,
                "access_key": self._access_key,
                "input": self.input_buckets,
                "output": self.output_buckets,
            }
        else:
            return {}

    def _create_bucket(self, name: str, buckets: List[str] = []):
        for bucket_name in self.buckets:
            if name in bucket_name:
                self.logging.info(
                    "Bucket {} for {} already exists, skipping.".format(bucket_name, name)
                )
                return bucket_name
        # minio has limit of bucket name to 16 characters
        bucket_name = "{}-{}".format(name, str(uuid.uuid4())[0:16])
        try:
            self.connection.make_bucket(bucket_name, location=self.location)
            self.logging.info("Created bucket {}".format(bucket_name))
            return bucket_name
        except (
            minio.error.BucketAlreadyOwnedByYou,
            minio.error.BucketAlreadyExists,
            minio.error.ResponseError,
        ) as err:
            self.logging.error("Bucket creation failed!")
            # rethrow
            raise err

    def uploader_func(self, bucket_idx, file, filepath):
        try:
            self.connection.fput_object(self.input_buckets[bucket_idx], file, filepath)
        except minio.error.ResponseError as err:
            self.logging.error("Upload failed!")
            raise (err)

    def clean(self):
        for bucket in self.output_buckets:
            objects = self.connection.list_objects_v2(bucket)
            objects = [obj.object_name for obj in objects]
            for err in self.connection.remove_objects(bucket, objects):
                self.logging.error("Deletion Error: {}".format(del_err))

    def download_results(self, result_dir):
        result_dir = os.path.join(result_dir, "storage_output")
        for bucket in self.output_buckets:
            objects = self.connection.list_objects_v2(bucket)
            objects = [obj.object_name for obj in objects]
            for obj in objects:
                self.connection.fget_object(bucket, obj, os.path.join(result_dir, obj))

    def clean_bucket(self, bucket: str):
        delete_object_list = map(
            lambda x: minio.DeleteObject(x.object_name),
            self.connection.list_objects(bucket_name=bucket),
        )
        errors = self.connection.remove_objects(bucket, delete_object_list)
        for error in errors:
            self.logging.error("Error when deleting object from bucket {}: {}!", bucket, error)

    def correct_name(self, name: str) -> str:
        return name

    def download(self, bucket_name: str, key: str, filepath: str):
        raise NotImplementedError()

    def list_bucket(self, bucket_name: str):
        raise NotImplementedError()

    def list_buckets(self, bucket_name: str) -> List[str]:
        buckets = self.connection.list_buckets()
        return [bucket.name for bucket in buckets if bucket_name in bucket.name]

    def upload(self, bucket_name: str, filepath: str, key: str):
        raise NotImplementedError()
