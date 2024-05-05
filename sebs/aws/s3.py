import os
import uuid
from typing import List, Optional

import boto3

from sebs.cache import Cache
from sebs.faas.config import Resources
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
        resources: Resources,
        location: str,
        access_key: str,
        secret_key: str,
        replace_existing: bool,
    ):
        super().__init__(location, cache_client, resources, replace_existing)
        self.client = session.client(
            "s3",
            region_name=location,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        self.cached = False

    def correct_name(self, name: str) -> str:
        return name

    def _create_bucket(
        self, name: str, buckets: List[str] = [], randomize_name: bool = False
    ) -> str:
        for bucket_name in buckets:
            if name in bucket_name:
                self.logging.info(
                    "Bucket {} for {} already exists, skipping.".format(bucket_name, name)
                )
                return bucket_name

        if randomize_name:
            random_name = str(uuid.uuid4())[0:16]
            bucket_name = "{}-{}".format(name, random_name)
        else:
            bucket_name = name

        try:
            # this is incredible
            # https://github.com/boto/boto3/issues/125
            if self.region != "us-east-1":
                self.client.create_bucket(
                    Bucket=bucket_name,
                    CreateBucketConfiguration={"LocationConstraint": self.region},
                )
            else:
                # This is incredible x2 - boto3 will not throw exception if you recreate
                # a bucket in us-east-1
                # https://github.com/boto/boto3/issues/4023
                buckets = self.list_buckets()
                if bucket_name in buckets:
                    self.logging.error(
                        f"The bucket {bucket_name} not successful; it exists already"
                    )
                    raise RuntimeError(f"Bucket {bucket_name} already exists")
                self.client.create_bucket(Bucket=bucket_name)

            self.logging.info("Created bucket {}".format(bucket_name))
        except self.client.exceptions.BucketAlreadyExists as e:
            self.logging.error(f"The bucket {bucket_name} exists already in region {self.region}!")
            raise e
        except self.client.exceptions.ClientError as e:
            self.logging.error(
                f"The bucket {bucket_name} not successful; perhaps it exists already in a region "
                f" different from {self.region}?"
            )
            self.logging.error(e)
            raise e

        return bucket_name

    def uploader_func(self, path_idx, key, filepath):
        # Skip upload when using cached buckets and not updating storage.
        if self.cached and not self.replace_existing:
            return

        key = os.path.join(self.input_prefixes[path_idx], key)

        bucket_name = self.get_bucket(Resources.StorageBucketType.BENCHMARKS)
        if not self.replace_existing:
            for f in self.input_prefixes_files[path_idx]:
                f_name = f
                if key == f_name:
                    self.logging.info("Skipping upload of {} to {}".format(filepath, bucket_name))
                    return

        self.upload(bucket_name, filepath, key)

    def upload(self, bucket_name: str, filepath: str, key: str):
        self.logging.info("Upload {} to {}".format(filepath, bucket_name))
        self.client.upload_file(Filename=filepath, Bucket=bucket_name, Key=key)

    def download(self, bucket_name: str, key: str, filepath: str):
        self.logging.info("Download {}:{} to {}".format(bucket_name, key, filepath))
        self.client.download_file(Bucket=bucket_name, Key=key, Filename=filepath)

    def exists_bucket(self, bucket_name: str) -> bool:
        try:
            self.client.head_bucket(Bucket=bucket_name)
            return True
        except self.client.exceptions.ClientError:
            return False

    def list_bucket(self, bucket_name: str, prefix: str = ""):
        objects_list = self.client.list_objects_v2(Bucket=bucket_name, Prefix=prefix)
        objects: List[str]
        if "Contents" in objects_list:
            objects = [obj["Key"] for obj in objects_list["Contents"]]
        else:
            objects = []
        return objects

    def list_buckets(self, bucket_name: Optional[str] = None) -> List[str]:
        s3_buckets = self.client.list_buckets()["Buckets"]
        if bucket_name is not None:
            return [bucket["Name"] for bucket in s3_buckets if bucket_name in bucket["Name"]]
        else:
            return [bucket["Name"] for bucket in s3_buckets]

    def clean_bucket(self, bucket: str):
        objects = self.client.list_objects_v2(Bucket=bucket)
        if "Contents" in objects:
            objects = [{"Key": obj["Key"]} for obj in objects["Contents"]]  # type: ignore
            self.client.delete_objects(Bucket=bucket, Delete={"Objects": objects})  # type: ignore

    def remove_bucket(self, bucket: str):
        self.client.delete_bucket(Bucket=bucket)
