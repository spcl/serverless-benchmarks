import os

from abc import ABC
from abc import abstractmethod
from typing import List, Tuple, Optional

from sebs.cache import Cache
from sebs.utils import LoggingBase

"""
    Abstract class
"""


class PersistentStorage(ABC, LoggingBase):
    @staticmethod
    @abstractmethod
    def deployment_name() -> str:
        pass

    @property
    def cache_client(self) -> Cache:
        return self._cache_client

    @property
    def replace_existing(self):
        return self._replace_existing

    @replace_existing.setter
    def replace_existing(self, val: bool):
        self._replace_existing = val

    @property
    def region(self):
        return self._region

    def __init__(self, region: str, cache_client: Cache, replace_existing: bool):
        super().__init__()
        self._cache_client = cache_client
        self.cached = False
        self.input_buckets: List[str] = []
        self.output_buckets: List[str] = []
        self.input_buckets_files: List[List[str]] = []
        self._replace_existing = replace_existing
        self._region = region
        self._experiments_bucket: Optional[str] = None

    @property
    def input(self) -> List[str]:  # noqa: A003
        return self.input_buckets

    @property
    def output(self) -> List[str]:
        return self.output_buckets

    @abstractmethod
    def correct_name(self, name: str) -> str:
        pass

    @abstractmethod
    def _create_bucket(self, name: str, buckets: List[str] = []):
        pass

    """
        Some cloud systems might require additional suffixes to be
        added to a bucket name.
        For example, on AWS all bucket names are globally unique.
        Thus, we need to add region as a suffix.

        :return: suffix, might be empty
    """

    def _bucket_name_suffix(self) -> str:
        return ""

    def add_bucket(self, name: str, suffix: str, buckets: List[str]) -> Tuple[str, int]:

        cloud_suffix = self._bucket_name_suffix()
        if cloud_suffix:
            name = self.correct_name(f"{name}-{len(buckets)}-{cloud_suffix}-{suffix}")
        else:
            name = self.correct_name(f"{name}-{len(buckets)}-{suffix}")
        # there's cached bucket we could use
        for idx, bucket in enumerate(buckets):
            if name in bucket:
                return bucket, idx
        bucket_name = self._create_bucket(name)
        buckets.append(bucket_name)
        return bucket_name, len(buckets) - 1

    """
        Add an input bucket or retrieve an existing one.
        Bucket name format: name-idx-input

        :param name: bucket name
        :param cache: use cache storage for buckets when true
        :return: bucket name and index
    """

    def add_input_bucket(self, name: str) -> Tuple[str, int]:
        return self.add_bucket(name, "input", self.input_buckets)

    """
        Add an input bucket or retrieve an existing one.
        Bucket name format: name-idx-suffix

        :param name: bucket name
        :param suffix: bucket name suffix
        :param cache: use cache storage for buckets when true
        :return: bucket name and index
    """

    def add_output_bucket(self, name: str, suffix: str = "output") -> Tuple[str, int]:
        return self.add_bucket(name, suffix, self.output_buckets)

    """
        Download a file from a bucket.

        :param bucket_name:
        :param key: storage source filepath
        :param filepath: local destination filepath
    """

    @abstractmethod
    def download(self, bucket_name: str, key: str, filepath: str) -> None:
        pass

    """
        Upload a file to a bucket with by passing caching.
        Useful for uploading code package to storage (when required).

        :param bucket_name:
        :param filepath: local source filepath
        :param key: storage destination filepath
    """

    @abstractmethod
    def upload(self, bucket_name: str, filepath: str, key: str):
        pass

    """
        Retrieves list of files in a bucket.

        :param bucket_name:
        :return: list of files in a given bucket
    """

    @abstractmethod
    def list_bucket(self, bucket_name: str) -> List[str]:
        pass

    @abstractmethod
    def list_buckets(self, bucket_name: str) -> List[str]:
        pass

    @abstractmethod
    def exists_bucket(self, bucket_name: str) -> bool:
        pass

    @abstractmethod
    def clean_bucket(self, bucket_name: str):
        pass

    """
        Allocate a set of input/output buckets for the benchmark.
        The routine checks the cache first to verify that buckets have not
        been allocated first.

        :param benchmark: benchmark name
        :param buckets: number of input and number of output buckets
    """

    def allocate_buckets(self, benchmark: str, requested_buckets: Tuple[int, int]):

        # Load cached information
        cached_buckets = self.cache_client.get_storage_config(self.deployment_name(), benchmark)
        if cached_buckets:
            cache_valid = True
            for bucket in [
                *cached_buckets["buckets"]["input"],
                *cached_buckets["buckets"]["output"],
            ]:
                if not self.exists_bucket(bucket):
                    cache_valid = False
                    self.logging.info(f"Cached storage buckets {bucket} does not exist.")
                    break

            if cache_valid:
                self.input_buckets = cached_buckets["buckets"]["input"]
                for bucket in self.input_buckets:
                    self.input_buckets_files.append(self.list_bucket(bucket))
                self.output_buckets = cached_buckets["buckets"]["output"]
                # for bucket in self.output_buckets:
                #    self.clean_bucket(bucket)
                self.cached = True
                self.logging.info(
                    "Using cached storage input buckets {}".format(self.input_buckets)
                )
                self.logging.info(
                    "Using cached storage output buckets {}".format(self.output_buckets)
                )
                return
            else:
                self.logging.info("Cached storage buckets are no longer valid, creating new ones.")

        buckets = self.list_buckets(self.correct_name(benchmark))
        for i in range(0, requested_buckets[0]):
            self.input_buckets.append(
                self._create_bucket(self.correct_name("{}-{}-input".format(benchmark, i)), buckets)
            )
            self.input_buckets_files.append(self.list_bucket(self.input_buckets[-1]))
        for i in range(0, requested_buckets[1]):
            self.output_buckets.append(
                self._create_bucket(self.correct_name("{}-{}-output".format(benchmark, i)), buckets)
            )
        self.save_storage(benchmark)

    def experiments_bucket(self) -> str:

        if not self._experiments_bucket:
            pass

        return self._experiments_bucket

    """
        Implements a handy routine for uploading input data by benchmarks.
        It should skip uploading existing files unless storage client has been
        initialized to override existing data.

        :param bucket_idx: index of input bucket
        :param file: name of file to upload
        :param filepath: filepath in the storage
    """

    @abstractmethod
    def uploader_func(self, bucket_idx: int, file: str, filepath: str) -> None:
        pass

    """
        Save benchmark input/output buckets to cache.
    """

    def save_storage(self, benchmark: Optional[str]):

        if benchmark is not None:
            self.cache_client.update_storage(
                self.deployment_name(),
                benchmark,
                {"buckets": {"input": self.input, "output": self.output}},
            )
        self.cache_client.update_storage(
            self.deployment_name(),
            benchmark,
            {"buckets": {"input": self.input, "output": self.output}},
        )

    """
        Download all files in a storage bucket.
        Warning: assumes flat directory in a bucket! Does not handle bucket files
        with directory marks in a name, e.g. 'dir1/dir2/file'
    """

    def download_bucket(self, bucket_name: str, output_dir: str):

        files = self.list_bucket(bucket_name)
        for f in files:
            output_file = os.path.join(output_dir, f)
            if not os.path.exists(output_file):
                self.download(bucket_name, f, output_file)
