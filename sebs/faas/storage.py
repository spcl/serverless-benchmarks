import os
import re

from abc import ABC
from abc import abstractmethod
from typing import List, Optional, Tuple

from sebs.faas.config import Resources
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

    def __init__(
        self, region: str, cache_client: Cache, resources: Resources, replace_existing: bool
    ):
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
        return self._input_prefixes

    @property
    def output_prefixes(self) -> List[str]:
        return self._output_prefixes

    @abstractmethod
    def correct_name(self, name: str) -> str:
        pass

    def find_deployments(self) -> List[str]:

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
        pass

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
    def list_bucket(self, bucket_name: str, prefix: str = "") -> List[str]:
        pass

    @abstractmethod
    def list_buckets(self, bucket_name: Optional[str] = None) -> List[str]:
        pass

    @abstractmethod
    def exists_bucket(self, bucket_name: str) -> bool:
        pass

    @abstractmethod
    def clean_bucket(self, bucket_name: str):
        pass

    @abstractmethod
    def remove_bucket(self, bucket: str):
        pass

    """
        Allocate a set of input/output buckets for the benchmark.
        The routine checks the cache first to verify that buckets have not
        been allocated first.

        :param benchmark: benchmark name
        :param buckets: number of input and number of output buckets
    """

    def benchmark_data(
        self, benchmark: str, requested_buckets: Tuple[int, int]
    ) -> Tuple[List[str], List[str]]:

        """
        Add an input path inside benchmarks bucket.
        Bucket name format: name-idx-input
        """
        for i in range(0, requested_buckets[0]):
            self.input_prefixes.append("{}-{}-input".format(benchmark, i))

        """
            Add an input path inside benchmarks bucket.
            Bucket name format: name-idx-output
        """
        for i in range(0, requested_buckets[1]):
            self.output_prefixes.append("{}-{}-output".format(benchmark, i))

        cached_storage = self.cache_client.get_storage_config(self.deployment_name(), benchmark)
        self.cached = True

        if cached_storage is not None:

            cached_storage = cached_storage["buckets"]

            # verify the input is up to date
            for prefix in self.input_prefixes:
                if prefix not in cached_storage["input"]:
                    self.cached = False

            for prefix in self.output_prefixes:
                if prefix not in cached_storage["output"]:
                    self.cached = False
        else:
            self.cached = False

        if self.cached is True and cached_storage["input_uploaded"] is False:
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

    # def allocate_buckets(self, benchmark: str, requested_buckets: Tuple[int, int]):

    # benchmarks_bucket = self.benchmarks_bucket()

    # Load cached information
    # cached_buckets = self.cache_client.get_storage_config(self.deployment_name(), benchmark)
    # if cached_buckets:
    #    cache_valid = True
    #    for bucket in [
    #        *cached_buckets["buckets"]["input"],
    #        *cached_buckets["buckets"]["output"],
    #    ]:
    #        if not self.exists_bucket(bucket):
    #            cache_valid = False
    #            self.logging.info(f"Cached storage buckets {bucket} does not exist.")
    #            break

    #    if cache_valid:
    #        self.input_buckets = cached_buckets["buckets"]["input"]
    #        for bucket in self.input_buckets:
    #            self.input_buckets_files.append(self.list_bucket(bucket))
    #        self.output_buckets = cached_buckets["buckets"]["output"]
    #        # for bucket in self.output_buckets:
    #        #    self.clean_bucket(bucket)
    #        self.cached = True
    #        self.logging.info(
    #            "Using cached storage input buckets {}".format(self.input_buckets)
    #        )
    #        self.logging.info(
    #            "Using cached storage output buckets {}".format(self.output_buckets)
    #        )
    #        return
    #    else:
    #        self.logging.info("Cached storage buckets are no longer valid, creating new ones.")

    # buckets = self.list_buckets(self.correct_name(benchmark))
    # for i in range(0, requested_buckets[0]):
    #    self.input_buckets.append(
    #        self._create_bucket(self.correct_name("{}-{}-input".format(benchmark, i)), buckets)
    #    )
    #    self.input_buckets_files.append(self.list_bucket(self.input_buckets[-1]))
    # for i in range(0, requested_buckets[1]):
    #    self.output_buckets.append(
    #        self._create_bucket(self.correct_name("{}-{}-output".format(benchmark, i)), buckets)
    #    )
    # self.save_storage(benchmark)

    def get_bucket(self, bucket_type: Resources.StorageBucketType) -> str:

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
