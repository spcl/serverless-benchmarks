from abc import ABC
from abc import abstractmethod
from typing import List, Tuple


"""
    Abstract class
"""


class PersistentStorage(ABC):

    """
        :return: list of input buckets defined in the storage
    """

    @abstractmethod  # noqa: A003
    def input(self) -> List[str]:
        pass

    """
        Add an input bucket or retrieve an existing one.
        Bucket name format: name-idx-input

        :param name: bucket name
        :param cache: use cache storage for buckets when true
        :return: bucket name and index
    """

    @abstractmethod
    def add_input_bucket(self, name: str, cache: bool = True) -> Tuple[str, int]:
        pass

    """
        Add an input bucket or retrieve an existing one.
        Bucket name format: name-idx-suffix

        :param name: bucket name
        :param suffix: bucket name suffix
        :param cache: use cache storage for buckets when true
        :return: bucket name and index
    """

    @abstractmethod
    def add_output_bucket(
        self, name: str, suffix: str = "output", cache: bool = True
    ) -> Tuple[str, int]:
        pass

    """
        :return: list of output buckets defined in the storage
    """

    @abstractmethod
    def output(self) -> List[str]:
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
    def list_bucket(self, bucket_name: str) -> List[str]:
        pass

    """
        Allocate a set of input/output buckets for the benchmark.
        The routine checks the cache first to verify that buckets have not
        been allocated first.

        :param benchmark: benchmark name
        :param buckets: tuple of two values: number of input and number of output buckets
    """

    @abstractmethod
    def allocate_buckets(self, benchmark: str, buckets: Tuple[int, int]):
        pass

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
