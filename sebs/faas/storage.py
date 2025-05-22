import os
import re

from abc import ABC
from abc import abstractmethod
from typing import List, Optional, Tuple

from sebs.faas.config import Resources
from sebs.cache import Cache
from sebs.utils import LoggingBase

"""
Abstract base class for persistent storage services used by FaaS benchmarks.

This class defines the interface for interacting with storage services like
AWS S3, Azure Blob Storage, etc., for managing benchmark data, code packages,
and experiment results.
"""


class PersistentStorage(ABC, LoggingBase):
    """
    Abstract base class for FaaS persistent storage.

    Manages buckets/containers for benchmark data, deployment packages, and experiment results.
    Handles caching of storage configurations and interaction with the cloud provider's
    storage service.
    """
    @staticmethod
    @abstractmethod
    def deployment_name() -> str:
        """
        Return the name of the FaaS deployment this storage belongs to (e.g., "aws", "azure").

        :return: Deployment name string.
        """
        pass

    @property
    def cache_client(self) -> Cache:
        """The cache client instance for storing/retrieving storage configurations."""
        return self._cache_client

    @property
    def replace_existing(self) -> bool: # Made getter more explicit
        """Flag indicating whether to replace existing files in buckets."""
        return self._replace_existing

    @replace_existing.setter
    def replace_existing(self, val: bool):
        """Set the flag for replacing existing files."""
        self._replace_existing = val

    @property
    def region(self) -> str: # Added return type
        """The cloud region where the storage is located."""
        return self._region

    def __init__(
        self, region: str, cache_client: Cache, resources: Resources, replace_existing: bool
    ):
        """
        Initialize the PersistentStorage instance.

        :param region: The cloud region.
        :param cache_client: The cache client instance.
        :param resources: The cloud resources configuration object.
        :param replace_existing: Flag to control overwriting existing files.
        """
        super().__init__()
        self._cache_client = cache_client
        self.cached = False # Indicates if current benchmark's data/bucket info is from cache
        self._input_prefixes: List[str] = []
        self._output_prefixes: List[str] = []
        self.input_prefixes_files: List[List[str]] = []
        self._replace_existing = replace_existing
        self._region = region
        self._cloud_resources = resources

    @property
    def input_prefixes(self) -> List[str]:
        """List of input prefixes (paths within the benchmark data bucket)."""
        return self._input_prefixes

    @property
    def output_prefixes(self) -> List[str]:
        """List of output prefixes (paths within the benchmark data bucket)."""
        return self._output_prefixes

    @abstractmethod
    def correct_name(self, name: str) -> str:
        """
        Correct a bucket/container name to comply with provider-specific naming rules.

        :param name: The proposed name.
        :return: A valid name for the provider.
        """
        pass

    def find_deployments(self) -> List[str]:
        """
        Find existing SeBS deployments by listing buckets that match the benchmark bucket pattern.

        Looks for buckets named "sebs-benchmarks-*".

        :return: List of deployment identifiers (resource prefixes).
        """
        deployments = []
        buckets = self.list_buckets()
        for bucket in buckets:
            # The benchmarks bucket must exist in every deployment.
            deployment_search = re.match("sebs-benchmarks-(.*)", bucket)
            if deployment_search:
                deployments.append(deployment_search.group(1))
        return deployments

    @abstractmethod
    def _create_bucket(
        self, name: str, buckets: List[str] = [], randomize_name: bool = False
    ) -> str:
        """
        Internal implementation to create a new bucket/container.

        Should handle provider-specific creation logic, including name randomization
        and checking against existing buckets if necessary.

        :param name: The desired base name for the bucket.
        :param buckets: Optional list of existing bucket names to check against.
        :param randomize_name: If True, append a random string to the bucket name.
        :return: The name of the created bucket.
        """
        pass

    @abstractmethod
    def download(self, bucket_name: str, key: str, filepath: str) -> None:
        """
        Download a file from a bucket/container.

        :param bucket_name: Name of the bucket/container.
        :param key: The key/path of the object in the storage.
        :param filepath: The local path where the file should be saved.
        """
        pass

    @abstractmethod
    def upload(self, bucket_name: str, filepath: str, key: str):
        """
        Upload a file to a bucket/container, bypassing caching logic if necessary.

        Useful for uploading code packages or other essential files.

        :param bucket_name: Name of the bucket/container.
        :param filepath: Local path of the file to upload.
        :param key: The key/path where the object will be stored in the storage.
        """
        pass

    @abstractmethod
    def list_bucket(self, bucket_name: str, prefix: str = "") -> List[str]:
        """
        List files/objects in a given bucket/container, optionally filtered by prefix.

        :param bucket_name: Name of the bucket/container.
        :param prefix: Optional prefix to filter the listing.
        :return: A list of object keys/names.
        """
        pass

    @abstractmethod
    def list_buckets(self, bucket_name: Optional[str] = None) -> List[str]:
        """
        List all buckets/containers, or filter by a partial name.

        :param bucket_name: Optional string to filter bucket names (e.g., contains match).
        :return: List of bucket/container names.
        """
        pass

    @abstractmethod
    def exists_bucket(self, bucket_name: str) -> bool:
        """
        Check if a bucket/container with the given name exists.

        :param bucket_name: Name of the bucket/container.
        :return: True if it exists, False otherwise.
        """
        pass

    @abstractmethod
    def clean_bucket(self, bucket_name: str):
        """
        Delete all objects within a specified bucket/container.

        :param bucket_name: Name of the bucket/container to clean.
        """
        pass

    @abstractmethod
    def remove_bucket(self, bucket: str):
        """
        Delete an entire bucket/container. The bucket must typically be empty.

        :param bucket: Name of the bucket/container to delete.
        """
        pass

    def benchmark_data(
        self, benchmark: str, requested_buckets: Tuple[int, int]
    ) -> Tuple[List[str], List[str]]:
        """
        Prepare input and output prefixes for a benchmark within the benchmark data bucket.

        Checks cache for existing configurations and lists files if not cached or if
        input data is marked as not uploaded. Updates cache with current prefix info.

        Input prefixes are in the format: `{benchmark}-{idx}-input`
        Output prefixes are in the format: `{benchmark}-{idx}-output`

        :param benchmark: The name of the benchmark.
        :param requested_buckets: A tuple (num_input_prefixes, num_output_prefixes).
        :return: A tuple containing (list_of_input_prefixes, list_of_output_prefixes).
        """
        # Generate input prefixes
        for i in range(requested_buckets[0]):
            self.input_prefixes.append(f"{benchmark}-{i}-input")

        # Generate output prefixes
        for i in range(requested_buckets[1]):
            self.output_prefixes.append(f"{benchmark}-{i}-output")

        cached_storage = self.cache_client.get_storage_config(self.deployment_name(), benchmark)
        self.cached = True # Assume cached initially

        if cached_storage and "buckets" in cached_storage:
            cached_buckets_info = cached_storage["buckets"]
            # Verify if all requested input prefixes are in cache
            for prefix in self.input_prefixes:
                if prefix not in cached_buckets_info.get("input", []):
                    self.cached = False
                    break
            # Verify if all requested output prefixes are in cache
            if self.cached: # Only check if still considered cached
                for prefix in self.output_prefixes:
                    if prefix not in cached_buckets_info.get("output", []):
                        self.cached = False
                        break
            # Check if input was marked as uploaded
            if self.cached and not cached_buckets_info.get("input_uploaded", False):
                self.cached = False
        else:
            self.cached = False # No cache entry or no buckets in cache

        # If not fully cached or input needs re-uploading, list files for input prefixes
        if not self.cached:
            self.input_prefixes_files = [] # Reset
            benchmark_data_bucket = self.get_bucket(Resources.StorageBucketType.BENCHMARKS)
            for prefix in self.input_prefixes:
                self.input_prefixes_files.append(
                    self.list_bucket(benchmark_data_bucket, prefix)
                )

        # Update cache with current state
        self._cache_client.update_storage(
            self.deployment_name(),
            benchmark,
            {
                "buckets": {
                    "input": self.input_prefixes,
                    "output": self.output_prefixes,
                    "input_uploaded": self.cached, # Mark as uploaded if we didn't need to list files
                }
            },
        )
        return self.input_prefixes, self.output_prefixes

    def get_bucket(self, bucket_type: Resources.StorageBucketType) -> str:
        """
        Get or create a standard SeBS bucket of a specific type (BENCHMARKS, EXPERIMENTS, DEPLOYMENT).

        Checks if the bucket is already known in `_cloud_resources`. If not,
        generates the expected name, checks if it exists in the cloud, creates it
        if necessary, and then stores it in `_cloud_resources`.

        :param bucket_type: The type of bucket to get/create.
        :return: The name of the bucket.
        """
        bucket = self._cloud_resources.get_storage_bucket(bucket_type)
        if bucket is None:
            description_map = { # Renamed from `description` to avoid conflict
                Resources.StorageBucketType.BENCHMARKS: "benchmarks",
                Resources.StorageBucketType.EXPERIMENTS: "experiment results",
                Resources.StorageBucketType.DEPLOYMENT: "code deployment",
            }
            bucket_purpose_description = description_map[bucket_type]

            name = self._cloud_resources.get_storage_bucket_name(bucket_type)
            corrected_name = self.correct_name(name) # Ensure name is valid

            if not self.exists_bucket(corrected_name):
                self.logging.info(f"Initialize a new bucket for {bucket_purpose_description}")
                bucket = self._create_bucket(
                    corrected_name,
                    randomize_name=False, # Standard SeBS buckets are not randomized
                )
            else:
                self.logging.info(f"Using existing bucket {corrected_name} for {bucket_purpose_description}")
                bucket = corrected_name
            self._cloud_resources.set_storage_bucket(bucket_type, bucket)
        return bucket

    @abstractmethod
    def uploader_func(self, bucket_idx: int, file: str, filepath: str) -> None:
        """
        Abstract method for a function to upload a single file to a specific input prefix.

        This is often used as a target for multiprocessing uploads. Implementations
        should handle skipping existing files if `self.replace_existing` is False.

        :param bucket_idx: Index of the input prefix (from `self.input_prefixes`).
        :param file: Name of the file to upload (becomes part of the key).
        :param filepath: Local path of the file to upload.
        """
        pass

    def download_bucket(self, bucket_name: str, output_dir: str):
        """
        Download all files from a given bucket/container to a local directory.

        Warning: Assumes a flat directory structure within the bucket; does not
        handle objects with directory markers (e.g., 'dir1/dir2/file') correctly
        in terms of creating local subdirectories. Files are downloaded to `output_dir`.

        :param bucket_name: Name of the bucket/container to download from.
        :param output_dir: Local directory to save downloaded files.
        """
        files = self.list_bucket(bucket_name)
        for f_key in files: # Renamed f to f_key for clarity
            # Ensure the output path is just the filename part of the key
            # to avoid issues with keys containing paths if list_bucket returns full keys.
            local_filename = os.path.basename(f_key)
            output_file = os.path.join(output_dir, local_filename)
            if not os.path.exists(output_file):
                self.download(bucket_name, f_key, output_file)
