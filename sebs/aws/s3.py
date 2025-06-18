"""AWS S3 storage implementation for SeBS.

This module provides the S3 class which implements persistent storage functionality
for the Serverless Benchmarking Suite using Amazon S3. It handles bucket creation,
file upload/download operations, and caching for benchmark data storage.

Key classes:
    S3: AWS S3 persistent storage implementation
"""

import os
import uuid
from typing import List, Optional

import boto3

from sebs.cache import Cache
from sebs.faas.config import Resources
from ..faas.storage import PersistentStorage


class S3(PersistentStorage):
    """AWS S3 persistent storage implementation for SeBS.
    
    This class provides persistent storage functionality using Amazon S3.
    It handles bucket creation, file operations, and provides a unified
    interface for benchmark data storage and retrieval.
    
    Attributes:
        client: S3 client for AWS API operations
        cached: Whether bucket configurations are cached
    """
    
    @staticmethod
    def typename() -> str:
        """Get the type name for this storage system.
        
        Returns:
            str: Type name ('AWS.S3')
        """
        return "AWS.S3"

    @staticmethod
    def deployment_name() -> str:
        """Get the deployment name for this storage system.
        
        Returns:
            str: Deployment name ('aws')
        """
        return "aws"

    @property
    def replace_existing(self) -> bool:
        """Get whether to replace existing files.
        
        Returns:
            bool: True if existing files should be replaced, False otherwise
        """
        return self._replace_existing

    @replace_existing.setter
    def replace_existing(self, val: bool) -> None:
        """Set whether to replace existing files.
        
        Args:
            val: True to replace existing files, False otherwise
        """
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
    ) -> None:
        """Initialize S3 persistent storage.
        
        Args:
            session: AWS boto3 session
            cache_client: Cache client for storing bucket configurations
            resources: Cloud resource configuration
            location: AWS region name
            access_key: AWS access key ID
            secret_key: AWS secret access key
            replace_existing: Whether to replace existing files during uploads
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
        """Correct bucket name for S3 naming requirements.
        
        Args:
            name: Original bucket name
            
        Returns:
            str: Corrected bucket name (no changes for S3)
        """
        return name

    def _create_bucket(
        self, name: str, buckets: List[str] = [], randomize_name: bool = False
    ) -> str:
        """Create an S3 bucket with the specified name.
        
        Handles the complex S3 bucket creation logic including region-specific
        requirements and conflict resolution.
        
        Args:
            name: Desired bucket name
            buckets: List of existing buckets to check against
            randomize_name: Whether to append a random suffix to ensure uniqueness
            
        Returns:
            str: Name of the created bucket
            
        Raises:
            BucketAlreadyExists: If bucket already exists in the same region
            ClientError: If bucket creation fails for other reasons
            RuntimeError: If bucket already exists in us-east-1 region
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

    def uploader_func(self, path_idx: int, key: str, filepath: str) -> None:
        """Upload a file to S3 with caching and replacement logic.
        
        Handles the upload of benchmark files with appropriate caching behavior
        and replacement logic based on configuration.
        
        Args:
            path_idx: Index of the input path configuration
            key: S3 object key for the file
            filepath: Local path to the file to upload
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

    def upload(self, bucket_name: str, filepath: str, key: str) -> None:
        """Upload a file to S3.
        
        Args:
            bucket_name: Name of the S3 bucket
            filepath: Local path to the file to upload
            key: S3 object key for the uploaded file
        """
        self.logging.info("Upload {} to {}".format(filepath, bucket_name))
        self.client.upload_file(Filename=filepath, Bucket=bucket_name, Key=key)

    def download(self, bucket_name: str, key: str, filepath: str) -> None:
        """Download a file from S3.
        
        Args:
            bucket_name: Name of the S3 bucket
            key: S3 object key of the file to download
            filepath: Local path where the file should be saved
        """
        self.logging.info("Download {}:{} to {}".format(bucket_name, key, filepath))
        self.client.download_file(Bucket=bucket_name, Key=key, Filename=filepath)

    def exists_bucket(self, bucket_name: str) -> bool:
        """Check if an S3 bucket exists and is accessible.
        
        Args:
            bucket_name: Name of the bucket to check
            
        Returns:
            bool: True if bucket exists and is accessible, False otherwise
        """
        try:
            self.client.head_bucket(Bucket=bucket_name)
            return True
        except self.client.exceptions.ClientError:
            return False

    def list_bucket(self, bucket_name: str, prefix: str = "") -> List[str]:
        """List objects in an S3 bucket with optional prefix filtering.
        
        Args:
            bucket_name: Name of the S3 bucket
            prefix: Optional prefix to filter objects
            
        Returns:
            List[str]: List of object keys in the bucket
        """
        objects_list = self.client.list_objects_v2(Bucket=bucket_name, Prefix=prefix)
        objects: List[str]
        if "Contents" in objects_list:
            objects = [obj["Key"] for obj in objects_list["Contents"]]
        else:
            objects = []
        return objects

    def list_buckets(self, bucket_name: Optional[str] = None) -> List[str]:
        """List S3 buckets with optional name filtering.
        
        Args:
            bucket_name: Optional bucket name pattern to filter by
            
        Returns:
            List[str]: List of bucket names
        """
        s3_buckets = self.client.list_buckets()["Buckets"]
        if bucket_name is not None:
            return [bucket["Name"] for bucket in s3_buckets if bucket_name in bucket["Name"]]
        else:
            return [bucket["Name"] for bucket in s3_buckets]

    def clean_bucket(self, bucket: str) -> None:
        """Remove all objects from an S3 bucket.
        
        Args:
            bucket: Name of the bucket to clean
        """
        objects = self.client.list_objects_v2(Bucket=bucket)
        if "Contents" in objects:
            objects = [{"Key": obj["Key"]} for obj in objects["Contents"]]  # type: ignore
            self.client.delete_objects(Bucket=bucket, Delete={"Objects": objects})  # type: ignore

    def remove_bucket(self, bucket: str) -> None:
        """Delete an S3 bucket.
        
        Args:
            bucket: Name of the bucket to delete
            
        Note:
            The bucket must be empty before it can be deleted
        """
        self.client.delete_bucket(Bucket=bucket)
