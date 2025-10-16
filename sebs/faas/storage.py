"""Object storage abstraction for serverless benchmarks.

This module provides the PersistentStorage abstract base class for managing
object storage across different cloud platforms and local deployments. It
handles bucket management, file operations, and benchmark data organization.

The storage abstraction supports:
- Cross-platform object storage (S3, Azure Blob, GCS, MinIO)
- Benchmark data organization with input/output separation
- Bucket lifecycle management and naming conventions
- Benchmark files upload/download operations with caching
- Deployment discovery and resource management

Each platform provides concrete implementations that handle platform-specific
API calls while following the common interface defined here.
"""

import os
import re

from abc import ABC
from abc import abstractmethod
from typing import List, Optional, Tuple

from sebs.faas.config import Resources
from sebs.cache import Cache
from sebs.utils import LoggingBase


class PersistentStorage(ABC, LoggingBase):
    """Abstract base class for persistent object storage implementations.

    This class defines the interface for object storage services across different
    cloud platforms. It manages buckets, files, and benchmark data organization
    while providing a consistent API regardless of the underlying storage service.

    Attributes:
        cached: Whether bucket configuration is cached
        _cache_client: Cache client for storing configuration
        _input_prefixes: List of input data prefixes for benchmarks
        _output_prefixes: List of output data prefixes for benchmarks
        input_prefixes_files: Files associated with input prefixes
        _replace_existing: Whether to replace existing files during uploads
        _region: Cloud region for storage operations
        _cloud_resources: Resource configuration for the platform
    """

    @staticmethod
    @abstractmethod
    def deployment_name() -> str:
        """Return the name of the FaaS deployment this storage belongs to (e.g., "aws", "azure").

        Returns:
            str: Platform name (e.g., 'aws', 'azure', 'gcp', 'minio')
        """
        pass

    @property
    def cache_client(self) -> Cache:
        """Get the cache client for configuration storage.

        Returns:
            Cache: Cache client instance
        """
        return self._cache_client

    @property
    def replace_existing(self) -> bool:
        """Flag indicating whether to replace existing files during operations.

        Returns:
            bool: True if existing files should be replaced, False otherwise
        """
        return self._replace_existing

    @replace_existing.setter
    def replace_existing(self, val: bool):
        """Set flag indicating whether to replace existing files during operations.

        Args:
            val: True to replace existing files, False to skip
        """
        self._replace_existing = val

    @property
    def region(self) -> str:
        """Get the cloud region for storage operations.

        Returns:
            str: Cloud region identifier
        """
        return self._region

    def __init__(
        self, region: str, cache_client: Cache, resources: Resources, replace_existing: bool
    ):
        """Initialize the persistent storage instance.

        Args:
            region: Cloud region for storage operations
            cache_client: Cache client for configuration persistence
            resources: Resource configuration for the platform
            replace_existing: Whether to replace existing files during uploads
        """
        super().__init__()
        self._cache_client = cache_client
        self.cached = False
        self._input_prefixes: List[str] = []
        self._output_prefixes: List[str] = []
        self.input_prefixes_files: List[List[str]] = []
        self._replace_existing = replace_existing
        self._region = region
        self._cloud_resources = resources

    @property
    def input_prefixes(self) -> List[str]:
        """Get the list of input data prefixes for benchmarks.
        These are paths within the benchmark data bucket.

        Returns:
            List[str]: List of input prefix names
        """
        return self._input_prefixes

    @property
    def output_prefixes(self) -> List[str]:
        """Get the list of output data prefixes for benchmarks.
        These are paths within the benchmark data bucket.

        Returns:
            List[str]: List of output prefix names
        """
        return self._output_prefixes

    @abstractmethod
    def correct_name(self, name: str) -> str:
        """Correct a bucket name to comply with platform naming requirements.

        Different platforms have different naming restrictions (character sets,
        length limits, etc.). This method applies platform-specific corrections.

        Args:
            name: Original bucket name

        Returns:
            str: Corrected bucket name that complies with platform requirements
        """
        pass

    def find_deployments(self) -> List[str]:
        """Find existing SeBS deployments by scanning bucket names.

        Scans all buckets in the storage service and extracts deployment IDs
        from bucket names that follow the SeBS naming convention. This helps
        identify existing deployments that can be reused.

        Looks for buckets named "sebs-benchmarks-*".

        Returns:
            List[str]: List of deployment resource IDs found in bucket names
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
        self, name: str, buckets: Optional[List[str]] = None, randomize_name: bool = False
    ) -> str:
        """Create a new storage bucket with platform-specific implementation.

        Args:
            name: Desired bucket name
            buckets: Optional list of existing buckets to check against
            randomize_name: Whether to add random suffix for uniqueness

        Returns:
            str: Name of the created bucket

        Raises:
            Platform-specific exceptions for bucket creation failures
        """
        pass

    @abstractmethod
    def download(self, bucket_name: str, key: str, filepath: str) -> None:
        """Download a file from a storage bucket.

        Args:
            bucket_name: Name of the source bucket
            key: Storage source filepath (object key)
            filepath: Local destination filepath

        Raises:
            Platform-specific exceptions for download failures
        """
        pass

    @abstractmethod
    def upload(self, bucket_name: str, filepath: str, key: str) -> None:
        """Upload a file to a storage bucket.

        Bypasses caching and directly uploads the file. Useful for uploading
        code packages to storage when required by the deployment platform.

        Args:
            bucket_name: Name of the destination bucket
            filepath: Local source filepath
            key: Storage destination filepath (object key)

        Raises:
            Platform-specific exceptions for upload failures
        """
        pass

    @abstractmethod
    def list_bucket(self, bucket_name: str, prefix: str = "") -> List[str]:
        """Retrieve list of files in a storage bucket.

        Args:
            bucket_name: Name of the bucket to list
            prefix: Optional prefix to filter objects

        Returns:
            List[str]: List of file keys in the bucket matching the prefix

        Raises:
            Platform-specific exceptions for listing failures
        """
        pass

    @abstractmethod
    def list_buckets(self, bucket_name: Optional[str] = None) -> List[str]:
        """List all storage buckets/containers, optionally filtering
        them with a prefix.

        Args:
            bucket_name: Optional specific bucket prefix name to check for

        Returns:
            List[str]: List of bucket names. If bucket_name is provided,
                returns [bucket_name] if it exists, empty list otherwise.

        Raises:
            Platform-specific exceptions for listing failures
        """
        pass

    @abstractmethod
    def exists_bucket(self, bucket_name: str) -> bool:
        """Check if a storage bucket/container exists.

        Args:
            bucket_name: Name of the bucket to check

        Returns:
            bool: True if bucket exists, False otherwise

        Raises:
            Platform-specific exceptions for access failures
        """
        pass

    @abstractmethod
    def clean_bucket(self, bucket_name: str) -> None:
        """Remove all objects from a storage bucket.

        Args:
            bucket_name: Name of the bucket to clean

        Raises:
            Platform-specific exceptions for deletion failures
        """
        pass

    @abstractmethod
    def remove_bucket(self, bucket: str) -> None:
        """Delete a storage bucket completely.
        The bucket must often be emptied afterwards.

        Args:
            bucket: Name of the bucket to remove

        Raises:
            Platform-specific exceptions for deletion failures
        """
        pass

    def benchmark_data(
        self, benchmark: str, requested_buckets: Tuple[int, int]
    ) -> Tuple[List[str], List[str]]:
        """Allocate storage prefixes for benchmark input and output data.

        Creates logical prefixes within the benchmarks bucket for organizing
        benchmark input and output data. Checks cache first to avoid redundant
        allocation and validates existing prefix configuration.

        Prefix naming format:
        - Input: "benchmark-{idx}-input"
        - Output: "benchmark-{idx}-output"

        Args:
            benchmark: Name of the benchmark
            requested_buckets: Tuple of (input_prefix_count, output_prefix_count)

        Returns:
            Tuple[List[str], List[str]]: Lists of (input_prefixes, output_prefixes)
        """

        # Add input prefixes inside benchmarks bucket
        # Prefix format: name-idx-input
        for i in range(0, requested_buckets[0]):
            self.input_prefixes.append("{}-{}-input".format(benchmark, i))

        # Add output prefixes inside benchmarks bucket
        # Prefix format: name-idx-output
        for i in range(0, requested_buckets[1]):
            self.output_prefixes.append("{}-{}-output".format(benchmark, i))

        cached_storage = self.cache_client.get_storage_config(self.deployment_name(), benchmark)
        self.cached = True

        if cached_storage is not None:

            cached_buckets = cached_storage["buckets"]

            # verify the input is up to date
            for prefix in self.input_prefixes:
                if prefix not in cached_buckets["input"]:
                    self.cached = False

            for prefix in self.output_prefixes:
                if prefix not in cached_buckets["output"]:
                    self.cached = False
        else:
            self.cached = False

        if cached_storage is not None and cached_storage["input_uploaded"] is False:
            self.cached = False

        # query buckets if the input prefixes changed, or the input is not up to date.
        if self.cached is False:

            for prefix in self.input_prefixes:
                self.input_prefixes_files.append(
                    self.list_bucket(
                        self.get_bucket(Resources.StorageBucketType.BENCHMARKS),
                        self.input_prefixes[-1],
                    )
                )

        self._cache_client.update_storage(
            self.deployment_name(),
            benchmark,
            {
                "buckets": {
                    "input": self.input_prefixes,
                    "output": self.output_prefixes,
                    "input_uploaded": self.cached,
                }
            },
        )

        return self.input_prefixes, self.output_prefixes

    def get_bucket(self, bucket_type: Resources.StorageBucketType) -> str:
        """Get or create a storage bucket for the specified type.


        Checks if the bucket is already known in `_cloud_resources`. If not,
        generates a bucket name following the standard naming convention,
        checks if it exists in the cloud, creates it
        if necessary, and then stores it in `_cloud_resources`.

        Args:
            bucket_type: Type of bucket to retrieve (BENCHMARKS, EXPERIMENTS, DEPLOYMENT)

        Returns:
            str: Name of the bucket for the specified type

        Raises:
            Platform-specific exceptions for bucket operations
        """

        bucket = self._cloud_resources.get_storage_bucket(bucket_type)
        if bucket is None:
            description = {
                Resources.StorageBucketType.BENCHMARKS: "benchmarks",
                Resources.StorageBucketType.EXPERIMENTS: "experiment results",
                Resources.StorageBucketType.DEPLOYMENT: "code deployment",
            }

            name = self._cloud_resources.get_storage_bucket_name(bucket_type)

            if not self.exists_bucket(name):
                self.logging.info(f"Initialize a new bucket for {description[bucket_type]}")
                bucket = self._create_bucket(
                    self.correct_name(name),
                    randomize_name=False,
                )
            else:
                self.logging.info(f"Using existing bucket {name} for {description[bucket_type]}")
                bucket = name
            self._cloud_resources.set_storage_bucket(bucket_type, bucket)

        return bucket

    @abstractmethod
    def uploader_func(self, bucket_idx: int, file: str, filepath: str) -> None:
        """Upload benchmark input data to storage with smart caching.

        Implements a utility function for uploading benchmark input data that
        respects caching preferences. Skips uploading existing files unless
        the storage client has been configured to override existing data.

        This is used by each benchmark to prepare input benchmark files.

        Args:
            bucket_idx: Index of the input prefix/bucket
            file: Name of the file to upload
            filepath: Storage destination filepath (object key)

        Raises:
            Platform-specific exceptions for upload failures
        """
        pass

    def download_bucket(self, bucket_name: str, output_dir: str) -> None:
        """Download all files from a storage bucket to a local directory.

        Downloads every file from the specified bucket to a local output directory.
        Only downloads files that don't already exist locally.

        Warning:
            Assumes flat directory structure in bucket. Does not handle object
            keys with directory separators (e.g., 'dir1/dir2/file').

        Args:
            bucket_name: Name of the bucket to download from
            output_dir: Local directory to download files to

        Raises:
            Platform-specific exceptions for download failures
        """

        files = self.list_bucket(bucket_name)
        for file_key in files:
            output_file = os.path.join(output_dir, file_key)
            if not os.path.exists(output_file):
                self.download(bucket_name, file_key, output_file)
