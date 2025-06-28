"""Google Cloud Storage implementation for SeBS.

This module provides the GCPStorage class that implements object storage operations
using Google Cloud Storage. It handles bucket management, file uploads/downloads,
and storage resource allocation for benchmarks and deployment artifacts.

Classes:
    GCPStorage: Google Cloud Storage implementation with bucket and blob management

Example:
    Using GCP storage for benchmark files:

        storage = GCPStorage(region, cache, resources, replace_existing=False)
        bucket = storage.add_benchmark_bucket("my-benchmark")
        storage.upload(bucket, "/path/to/file.zip", "benchmark-code.zip")
"""

import logging
import os
import uuid
from typing import List, Optional

import google.cloud.storage as gcp_storage
from google.api_core import exceptions

from sebs.cache import Cache
from sebs.faas.config import Resources
from ..faas.storage import PersistentStorage


class GCPStorage(PersistentStorage):
    """Google Cloud Storage implementation providing persistent storage.

    Handles bucket creation, file operations, and storage resource management
    for benchmarks, deployment artifacts, and experiment outputs.

    Attributes:
        client: Google Cloud Storage client instance
        cached: Whether storage operations use cached data
    """

    @staticmethod
    def typename() -> str:
        """Get the type name for this storage implementation.

        Returns:
            Type name string for GCP storage
        """
        return "GCP.GCPStorage"

    @staticmethod
    def deployment_name() -> str:
        """Get the deployment name for this storage implementation.

        Returns:
            Deployment name string 'gcp'
        """
        return "gcp"

    @property
    def replace_existing(self) -> bool:
        """Flag indicating whether to replace existing files in buckets."""
        return self._replace_existing

    @replace_existing.setter
    def replace_existing(self, val: bool):
        """Set the flag for replacing existing files."""
        self._replace_existing = val

    def __init__(
        self, region: str, cache_client: Cache, resources: Resources, replace_existing: bool
    ) -> None:
        """Initialize GCP Storage client.

        Args:
            region: GCP region for storage resources
            cache_client: Cache instance for storing storage state
            resources: Resource configuration
            replace_existing: Whether to replace existing files during uploads
        """
        super().__init__(region, cache_client, resources, replace_existing)
        self.replace_existing = replace_existing
        self.client = gcp_storage.Client()
        self.cached = False

    def correct_name(self, name: str) -> str:
        """Correct bucket name to meet GCP naming requirements.
        Currently it does nothing - no special requirements on GCP.

        Args:
            name: Original bucket name

        Returns:
            Corrected bucket name (no changes needed for GCP)
        """
        return name

    def _create_bucket(
        self, name: str, buckets: Optional[List[str]] = None, randomize_name: bool = False
    ) -> str:
        """Create a new Cloud Storage bucket or return existing one.

        Checks if a bucket with a similar name (if `name` is a prefix) already exists
        in the provided `buckets` list. If `randomize_name` is True, appends a
        random string to make the name unique.

        Args:
            name: Base name for the bucket
            buckets: List of existing bucket names to check
            randomize_name: Whether to append random suffix to avoid name conflicts

        Returns:
            Name of the created or existing bucket
        """

        if buckets is None:
            buckets = []

        found_bucket = False
        for bucket_name in buckets:
            if name in bucket_name:
                found_bucket = True
                break

        if not found_bucket:

            if randomize_name:
                random_name = str(uuid.uuid4())[0:16]
                bucket_name = "{}-{}".format(name, random_name).replace(".", "_")
            else:
                bucket_name = name

            self.client.create_bucket(bucket_name)
            logging.info("Created bucket {}".format(bucket_name))
            return bucket_name
        else:
            logging.info("Bucket {} for {} already exists, skipping.".format(bucket_name, name))
            return bucket_name

    def download(self, bucket_name: str, key: str, filepath: str) -> None:
        """Download a file from Cloud Storage.

        Args:
            bucket_name: Name of the storage bucket
            key: Object key/path in the bucket
            filepath: Local file path to save the downloaded file
        """
        logging.info("Download {}:{} to {}".format(bucket_name, key, filepath))
        bucket_instance = self.client.bucket(bucket_name)
        blob = bucket_instance.blob(key)
        blob.download_to_filename(filepath)

    def upload(self, bucket_name: str, filepath: str, key: str) -> None:
        """Upload a file to Cloud Storage.

        Args:
            bucket_name: Name of the storage bucket
            filepath: Local file path to upload
            key: Object key/path in the bucket for the uploaded file
        """
        logging.info("Upload {} to {}".format(filepath, bucket_name))
        bucket_instance = self.client.bucket(bucket_name)
        blob = bucket_instance.blob(key, chunk_size=4 * 1024 * 1024)
        gcp_storage.blob._MAX_MULTIPART_SIZE = 5 * 1024 * 1024  # workaround for connection timeout
        blob.upload_from_filename(filepath)

    def exists_bucket(self, bucket_name: str) -> bool:
        """Check if a Cloud Storage bucket exists.

        Handles `exceptions.Forbidden` which can occur if the bucket exists
        but is not accessible by the current credentials (treated as not existing
        for SeBS purposes).

        Args:
            bucket_name: Name of the bucket to check

        Returns:
            True if bucket exists and is accessible, False otherwise
        """
        try:
            return self.client.bucket(bucket_name).exists()
        # 403 returned when the bucket exists but is owned by another user
        except exceptions.Forbidden:
            return False

    def list_bucket(self, bucket_name: str, prefix: str = "") -> List[str]:
        """List objects in a Cloud Storage bucket with optional prefix filter.

        Args:
            bucket_name: Name of the bucket to list
            prefix: Optional prefix to filter objects

        Returns:
            List of object names in the bucket matching the prefix
        """
        bucket_instance = self.client.get_bucket(bucket_name)
        all_blobs = list(self.client.list_blobs(bucket_instance))
        blobs = [blob.name for blob in all_blobs if prefix in blob.name]
        return blobs

    def list_buckets(self, bucket_name: Optional[str] = None) -> List[str]:
        """List Cloud Storage buckets, optionally filtered by name.

        Args:
            bucket_name: Optional bucket name filter

        Returns:
            List of bucket names, filtered if bucket_name is provided
        """
        all_buckets = list(self.client.list_buckets())
        if bucket_name is not None:
            buckets = [bucket.name for bucket in all_buckets if bucket_name in bucket.name]
        else:
            buckets = [bucket.name for bucket in all_buckets]
        return buckets

    def remove_bucket(self, bucket_name: str) -> None:
        """Remove a Cloud Storage bucket.

        Args:
            bucket_name: Name of the bucket to remove
        """
        self.client.get_bucket(bucket_name).delete()

    def clean_bucket(self, bucket: str) -> None:
        """Clean all objects from a Cloud Storage bucket.

        Args:
            bucket: Name of the bucket to clean

        Raises:
            NotImplementedError: This method is not yet implemented
        """
        raise NotImplementedError()

    def uploader_func(self, path_idx: int, key: str, filepath: str) -> None:
        """Upload function for batch operations with caching support.

        Uploads a file to the appropriate benchmark bucket, respecting cache
        settings and replace_existing configuration.

        This is primarily used by benchmarks to upload input data.

        Args:
            path_idx: Index of the input path prefix
            key: Object key for the uploaded file
            filepath: Local file path to upload
        """
        if self.cached and not self.replace_existing:
            return

        key = os.path.join(self.input_prefixes[path_idx], key)
        bucket_name = self.get_bucket(Resources.StorageBucketType.BENCHMARKS)
        if not self.replace_existing:
            for blob in self.input_prefixes_files[path_idx]:
                if key == blob:
                    logging.info("Skipping upload of {} to {}".format(filepath, bucket_name))
                    return
        self.upload(bucket_name, filepath, key)
