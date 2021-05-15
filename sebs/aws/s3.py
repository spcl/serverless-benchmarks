import uuid
from typing import List

import boto3

from sebs.cache import Cache
from ..faas.storage import PersistentStorage


class S3(PersistentStorage):
    @staticmethod
    def typename() -> str:
        return "AWS.S3"

    @staticmethod
    def deployment_name():
        return "aws"

    @property
    def replace_existing(self) -> bool:
        return self._replace_existing

    @replace_existing.setter
    def replace_existing(self, val: bool):
        self._replace_existing = val

    def __init__(
        self,
        session: boto3.session.Session,
        cache_client: Cache,
        location: str,
        access_key: str,
        secret_key: str,
        replace_existing: bool,
    ):
        super().__init__(cache_client, replace_existing)
        self.client = session.client(
            "s3",
            region_name=location,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        self.cached = False

    def correct_name(self, name: str) -> str:
        return name

    def _create_bucket(self, name: str, buckets: List[str] = []):
        for bucket_name in buckets:
            if name in bucket_name:
                self.logging.info(
                    "Bucket {} for {} already exists, skipping.".format(bucket_name, name)
                )
                return bucket_name
        random_name = str(uuid.uuid4())[0:16]
        bucket_name = "{}-{}".format(name, random_name)
        self.client.create_bucket(Bucket=bucket_name)
        self.logging.info("Created bucket {}".format(bucket_name))
        return bucket_name

    def uploader_func(self, bucket_idx, key, filepath):
        # Skip upload when using cached buckets and not updating storage.
        if self.cached and not self.replace_existing:
            return
        bucket_name = self.input_buckets[bucket_idx]
        if not self.replace_existing:
            if "Contents" in self.input_buckets_files[bucket_idx]:
                for f in self.input_buckets_files[bucket_idx]["Contents"]:
                    f_name = f["Key"]
                    if key == f_name:
                        self.logging.info(
                            "Skipping upload of {} to {}".format(filepath, bucket_name)
                        )
                        return
        bucket_name = self.input_buckets[bucket_idx]
        self.upload(bucket_name, filepath, key)

    def upload(self, bucket_name: str, filepath: str, key: str):
        self.logging.info("Upload {} to {}".format(filepath, bucket_name))
        self.client.upload_file(Filename=filepath, Bucket=bucket_name, Key=key)

    def download(self, bucket_name: str, key: str, filepath: str):
        self.logging.info("Download {}:{} to {}".format(bucket_name, key, filepath))
        self.client.download_file(Bucket=bucket_name, Key=key, Filename=filepath)

    def list_bucket(self, bucket_name: str):
        objects_list = self.client.list_objects_v2(Bucket=bucket_name)
        objects: List[str]
        if "Contents" in objects_list:
            objects = [obj["Key"] for obj in objects_list["Contents"]]
        else:
            objects = []
        return objects

    def list_buckets(self, bucket_name: str) -> List[str]:
        s3_buckets = self.client.list_buckets()["Buckets"]
        return [bucket["Name"] for bucket in s3_buckets if bucket_name in bucket["Name"]]

    def clean_bucket(self, bucket: str):
        objects = self.client.list_objects_v2(Bucket=bucket)
        if "Contents" in objects:
            objects = [
                {"Key": obj["Key"]} for obj in objects["Contents"]  # type: ignore
            ]
            self.client.delete_objects(
                Bucket=bucket, Delete={"Objects": objects}  # type: ignore
            )
