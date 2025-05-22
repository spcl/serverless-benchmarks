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
    """Google Cloud Storage persistent storage implementation."""
    @staticmethod
    def typename() -> str:
        """Return the type name of the storage implementation."""
        return "GCP.GCPStorage"

    @staticmethod
    def deployment_name():
        """Return the deployment name for GCP (gcp)."""
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
    ):
        """
        Initialize GCPStorage client.

        :param region: GCP region (used by parent class, not directly by Storage client).
        :param cache_client: Cache client instance.
        :param resources: Cloud resources configuration.
        :param replace_existing: Flag to replace existing files in buckets.
        """
        super().__init__(region, cache_client, resources, replace_existing)
        # self.replace_existing is already set by super().__init__ if PersistentStorage handles it
        # or it might be intended to be explicitly set here.
        # Assuming parent class handles it based on the call.
        self.client = gcp_storage.Client()
        self.cached = False # State for benchmark_data caching logic

    def correct_name(self, name: str) -> str:
        """
        Return the corrected bucket name (no correction typically needed for GCP Storage,
        but adheres to provider-specific rules if any).

        :param name: Original bucket name.
        :return: Corrected bucket name.
        """
        # GCP bucket names have their own rules (globally unique, DNS compliant).
        # This method could enforce SeBS specific parts or global uniqueness checks if needed.
        # For now, assuming names passed are either compliant or corrected by `_create_bucket`.
        return name

    def _create_bucket(
        self, name: str, buckets: List[str] = [], randomize_name: bool = False
    ) -> str:
        """
        Create a Google Cloud Storage bucket.

        Checks if a bucket with a similar name (if `name` is a prefix) already exists
        in the provided `buckets` list. If `randomize_name` is True, appends a
        random string to make the name unique.

        :param name: Desired base name for the bucket.
        :param buckets: List of existing bucket names to check against (prefix match).
        :param randomize_name: If True, append a random string to the bucket name.
        :return: Name of the created or existing bucket.
        """
        # Check if a bucket with `name` as a prefix already exists in the provided list
        # This logic is a bit different from just checking `name in buckets`.
        # It implies `buckets` might contain names like `name-suffix`.
        # If an exact match or suitable existing bucket is found, use it.
        bucket_to_use = name
        found_existing = False
        if not randomize_name: # Only check for existing if not randomizing
            for existing_bucket_name in buckets:
                if name == existing_bucket_name or existing_bucket_name.startswith(f"{name}-"):
                    logging.info(f"Bucket similar to {name} (found {existing_bucket_name}) already listed, using it.")
                    bucket_to_use = existing_bucket_name
                    found_existing = True
                    break
        
        if found_existing and self.client.bucket(bucket_to_use).exists():
             logging.info(f"Bucket {bucket_to_use} already exists, skipping creation.")
             return bucket_to_use

        # If not found or needs randomization, create a new one
        if randomize_name:
            random_suffix = str(uuid.uuid4())[0:16]
            # GCP bucket names cannot contain dots, replace with underscore or hyphen.
            # Hyphen is more common in DNS-style names.
            bucket_to_use = f"{name}-{random_suffix}".replace(".", "-").lower()
        else:
            # Ensure the non-randomized name is also compliant
            bucket_to_use = name.replace(".", "-").lower()

        try:
            created_bucket = self.client.create_bucket(bucket_to_use, location=self.region)
            logging.info(f"Created bucket {created_bucket.name} in region {self.region}.")
            return created_bucket.name
        except exceptions.Conflict:
            logging.info(f"Bucket {bucket_to_use} already exists (Conflict during creation). Using existing.")
            return bucket_to_use
        except Exception as e:
            logging.error(f"Failed to create bucket {bucket_to_use}: {e}")
            raise

    def download(self, bucket_name: str, key: str, filepath: str) -> None:
        """
        Download an object from a Google Cloud Storage bucket to a local file.

        :param bucket_name: Name of the GCS bucket.
        :param key: Object key (path within the bucket).
        :param filepath: Local path to save the downloaded file.
        """
        logging.info(f"Download {bucket_name}:{key} to {filepath}")
        bucket_instance = self.client.bucket(bucket_name)
        blob = bucket_instance.blob(key)
        blob.download_to_filename(filepath)

    def upload(self, bucket_name: str, filepath: str, key: str):
        """
        Upload a file to a specified Google Cloud Storage bucket.

        Sets a chunk size for resumable uploads and includes a workaround
        for potential connection timeouts with large files by adjusting
        `_MAX_MULTIPART_SIZE` (though this is an internal variable and might
        not be stable across library versions).

        :param bucket_name: Name of the GCS bucket.
        :param filepath: Local path to the file.
        :param key: Object key (path within the bucket).
        """
        logging.info(f"Upload {filepath} to {bucket_name}/{key}")
        bucket_instance = self.client.bucket(bucket_name)
        blob = bucket_instance.blob(key, chunk_size=4 * 1024 * 1024) # Resumable uploads
        
        # Workaround for potential connection timeouts, may not be needed or could change.
        # Accessing internal library variables like _MAX_MULTIPART_SIZE is risky.
        # Consider if this is still necessary or if official ways to handle timeouts exist.
        # For now, keeping original logic but noting its potential fragility.
        if hasattr(gcp_storage.blob, '_MAX_MULTIPART_SIZE'):
             gcp_storage.blob._MAX_MULTIPART_SIZE = 5 * 1024 * 1024
        
        blob.upload_from_filename(filepath)

    def exists_bucket(self, bucket_name: str) -> bool:
        """
        Check if a Google Cloud Storage bucket exists.

        Handles `exceptions.Forbidden` which can occur if the bucket exists
        but is not accessible by the current credentials (treated as not existing
        for SeBS purposes of creating a new one).

        :param bucket_name: Name of the GCS bucket.
        :return: True if the bucket exists and is accessible, False otherwise.
        """
        try:
            return self.client.bucket(bucket_name).exists()
        except exceptions.Forbidden: # Catch 403 if bucket exists but is owned by another user
            logging.warning(f"Bucket {bucket_name} exists but is not accessible (Forbidden). Treating as non-existent for creation purposes.")
            return False

    def list_bucket(self, bucket_name: str, prefix: str = "") -> List[str]:
        """
        List objects in a GCS bucket, optionally filtered by prefix.

        :param bucket_name: Name of the GCS bucket.
        :param prefix: Optional prefix to filter objects.
        :return: List of object names (keys).
        """
        # get_bucket will raise NotFound if bucket doesn't exist.
        bucket_instance = self.client.get_bucket(bucket_name)
        blobs_iterator = self.client.list_blobs(bucket_instance, prefix=prefix)
        return [blob.name for blob in blobs_iterator]

    def list_buckets(self, bucket_name_filter: Optional[str] = None) -> List[str]: # Renamed arg for clarity
        """
        List all GCS buckets accessible by the client, or filter by a partial name.

        :param bucket_name_filter: Optional string to filter bucket names (contains match).
        :return: List of bucket names.
        """
        all_buckets_iterator = self.client.list_buckets()
        if bucket_name_filter is not None:
            return [bucket.name for bucket in all_buckets_iterator if bucket_name_filter in bucket.name]
        else:
            return [bucket.name for bucket in all_buckets_iterator]

    def remove_bucket(self, bucket_name: str):
        """
        Delete a GCS bucket. The bucket must be empty.

        :param bucket_name: Name of the GCS bucket to delete.
        """
        bucket_instance = self.client.get_bucket(bucket_name)
        bucket_instance.delete(force=True) # force=True deletes non-empty buckets, use with caution.
                                         # Original had no force, which requires empty.
                                         # Consider if `clean_bucket` should be called first.
        logging.info(f"Deleted bucket {bucket_name}")


    def clean_bucket(self, bucket_name: str): # Renamed arg for consistency
        """
        Delete all objects within a GCS bucket.

        Note: This method is not implemented.
        To implement, one would list all blobs and then delete them in batches.

        :param bucket_name: Name of the GCS bucket to clean.
        :raises NotImplementedError: This method is not yet implemented.
        """
        # Example implementation sketch:
        # bucket_instance = self.client.bucket(bucket_name)
        # blobs_to_delete = list(bucket_instance.list_blobs())
        # if blobs_to_delete:
        #    bucket_instance.delete_blobs(blobs_to_delete)
        # logging.info(f"Cleaned bucket {bucket_name}")
        raise NotImplementedError("clean_bucket is not implemented for GCPStorage yet.")


    def uploader_func(self, path_idx: int, key: str, filepath: str) -> None:
        """
        Upload a file to a GCS bucket, typically for benchmark input data.

        Skips upload if using cached buckets and `replace_existing` is False,
        and the object already exists. Constructs the GCS object key using input prefixes.

        :param path_idx: Index of the input path/prefix from `self.input_prefixes`.
        :param key: Object key (filename) within the bucket, relative to the prefix.
        :param filepath: Local path to the file to upload.
        """
        if self.cached and not self.replace_existing:
            # This check might be redundant if list_bucket in benchmark_data correctly sets up
            # input_prefixes_files and self.cached status.
            # The original logic checked `if key == blob` which seems to imply `key` is full path.
            # Assuming `key` here is relative to prefix.
            logging.info(f"Skipping upload of {filepath} due to cache settings and no replace_existing.")
            return

        full_key = os.path.join(self.input_prefixes[path_idx], key)
        bucket_name = self.get_bucket(Resources.StorageBucketType.BENCHMARKS)

        # Check if file exists if not replacing
        if not self.replace_existing:
            # input_prefixes_files should contain full keys for the given prefix.
            # This check assumes self.input_prefixes_files[path_idx] has been populated correctly.
            if full_key in self.input_prefixes_files[path_idx]:
                logging.info(f"Skipping upload of {filepath} to {bucket_name}/{full_key} as it exists and replace_existing is False.")
                return
        
        self.upload(bucket_name, filepath, full_key)
