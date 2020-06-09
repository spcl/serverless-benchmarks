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
        :return: bucket name and index
    """

    @abstractmethod
    def add_input_bucket(self, name: str) -> Tuple[str, int]:
        pass

    """
        :return: list of output buckets defined in the storage
    """

    @abstractmethod
    def output(self) -> List[str]:
        pass

    @abstractmethod
    def download(self, bucket_name: str, file: str, filepath: str) -> None:
        pass

    """
        :param bucket_name:
        :return: list of files in a given bucket
    """

    @abstractmethod
    def list_bucket(self, bucket_name: str) -> List[str]:
        pass

    @abstractmethod
    def allocate_buckets(self, benchmark: str, buckets: Tuple[int, int]):
        pass

    @abstractmethod
    def uploader_func(self, bucket_idx: int, file: str, filepath: str) -> None:
        pass
