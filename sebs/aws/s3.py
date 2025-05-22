import os
import uuid
from typing import List, Optional

import boto3

from sebs.cache import Cache
from sebs.faas.config import Resources
from ..faas.storage import PersistentStorage


class S3(PersistentStorage):
    """AWS S3 persistent storage implementation."""
    @staticmethod
    def typename() -> str:
        """Return the type name of the storage implementation."""
        return "AWS.S3"

    @staticmethod
    def deployment_name():
        """Return the deployment name for AWS (aws)."""
        return "aws"

    @property
    def replace_existing(self) -> bool:
        """Flag indicating whether to replace existing files in buckets."""
        return self._replace_existing

    @replace_existing.setter
    def replace_existing(self, val: bool):
        """Set the flag for replacing existing files."""
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
        """
        Initialize S3 client.

        :param session: Boto3 session.
        :param cache_client: Cache client instance.
        :param resources: Cloud resources configuration.
        :param location: AWS region for the S3 client.
        :param access_key: AWS access key ID.
        :param secret_key: AWS secret access key.
        :param replace_existing: Flag to replace existing files in buckets.
        """
        super().__init__(location, cache_client, resources, replace_existing)
        self.client = session.client(
            "s3",
            region_name=location,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        self.cached = False

    def correct_name(self, name: str) -> str:
        """
        Return the corrected bucket name (no correction needed for S3).

        :param name: Original bucket name.
        :return: Corrected bucket name.
        """
        return name

    def _create_bucket(
        self, name: str, buckets: List[str] = [], randomize_name: bool = False
    ) -> str:
        """
        Create an S3 bucket.

        Handles bucket naming (randomization if requested) and region-specific
        creation logic. Checks if a similar bucket already exists.

        :param name: Desired base name for the bucket.
        :param buckets: List of existing bucket names to check against.
        :param randomize_name: If True, append a random string to the bucket name.
        :return: Name of the created or existing bucket.
        :raises RuntimeError: If bucket creation fails (e.g., already exists globally).
        """
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
                existing_buckets = self.list_buckets()
                if bucket_name in existing_buckets:
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

    def uploader_func(self, path_idx: int, key: str, filepath: str):
        """
        Upload a file to an S3 bucket, used as a callback for multiprocessing.

        Skips upload if using cached buckets and not replacing existing files.
        Constructs the S3 key using input prefixes.

        :param path_idx: Index of the input path/prefix.
        :param key: Object key (filename) within the bucket.
        :param filepath: Local path to the file to upload.
        """
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
        """
        Upload a file to a specified S3 bucket.

        :param bucket_name: Name of the S3 bucket.
        :param filepath: Local path to the file.
        :param key: Object key (path within the bucket).
        """
        self.logging.info("Upload {} to {}".format(filepath, bucket_name))
        self.client.upload_file(Filename=filepath, Bucket=bucket_name, Key=key)

    def download(self, bucket_name: str, key: str, filepath: str):
        """
        Download an object from an S3 bucket to a local file.

        :param bucket_name: Name of the S3 bucket.
        :param key: Object key (path within the bucket).
        :param filepath: Local path to save the downloaded file.
        """
        self.logging.info("Download {}:{} to {}".format(bucket_name, key, filepath))
        self.client.download_file(Bucket=bucket_name, Key=key, Filename=filepath)

    def exists_bucket(self, bucket_name: str) -> bool:
        """
        Check if an S3 bucket exists.

        :param bucket_name: Name of the S3 bucket.
        :return: True if the bucket exists, False otherwise.
        """
        try:
            self.client.head_bucket(Bucket=bucket_name)
            return True
        except self.client.exceptions.ClientError:
            return False

    def list_bucket(self, bucket_name: str, prefix: str = "") -> List[str]:
        """
        List objects in an S3 bucket, optionally filtered by prefix.

        :param bucket_name: Name of the S3 bucket.
        :param prefix: Optional prefix to filter objects.
        :return: List of object keys.
        """
        objects_list = self.client.list_objects_v2(Bucket=bucket_name, Prefix=prefix)
        objects: List[str]
        if "Contents" in objects_list:
            objects = [obj["Key"] for obj in objects_list["Contents"]]
        else:
            objects = []
        return objects

    def list_buckets(self, bucket_name: Optional[str] = None) -> List[str]:
        """
        List all S3 buckets, or filter by a partial name.

        :param bucket_name: Optional string to filter bucket names (contains match).
        :return: List of bucket names.
        """
        s3_buckets = self.client.list_buckets()["Buckets"]
        if bucket_name is not None:
            return [bucket["Name"] for bucket in s3_buckets if bucket_name in bucket["Name"]]
        else:
            return [bucket["Name"] for bucket in s3_buckets]

    def clean_bucket(self, bucket: str):
        """
        Delete all objects within an S3 bucket.

        :param bucket: Name of the S3 bucket to clean.
        """
        objects = self.client.list_objects_v2(Bucket=bucket)
        if "Contents" in objects:
            objects_to_delete = [{"Key": obj["Key"]} for obj in objects["Contents"]]  # type: ignore
            self.client.delete_objects(Bucket=bucket, Delete={"Objects": objects_to_delete})  # type: ignore

    def remove_bucket(self, bucket: str):
        """
        Delete an S3 bucket. The bucket must be empty.

        :param bucket: Name of the S3 bucket to delete.
        """
        self.client.delete_bucket(Bucket=bucket)
