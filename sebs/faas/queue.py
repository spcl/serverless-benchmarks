from abc import ABC
from abc import abstractmethod
from enum import Enum

from sebs.faas.config import Resources
from sebs.cache import Cache
from sebs.utils import LoggingBase

class Queue(ABC, LoggingBase):
    class QueueType(str, Enum):
        TRIGGER = "trigger"
        RESULT = "result"

        @staticmethod
        def deserialize(val: str) -> Queue.QueueType:
            for member in Queue.QueueType:
                if member.value == val:
                    return member
            raise Exception(f"Unknown queue type {val}")

    @staticmethod
    @abstractmethod
    def deployment_name() -> str:
        pass

    @property
    def cache_client(self) -> Cache:
        return self._cache_client

    @property
    def region(self):
        return self._region

    @property
    def queue_type(self):
        return self._queue_type

    @property
    def name(self):
        return self._name

    def __init__(self, benchmark: str, queue_type: Queue.QueueType, region: str, cache_client: Cache, resources: Resources):
        super().__init__()
        self._name = "{}-{}".format(benchmark, queue_type)
        self._queue_type = queue_type
        self._cache_client = cache_client
        self._cached = False
        self._region = region
        self._cloud_resources = resources

    @abstractmethod
    def create_queue(self):
        pass

    @abstractmethod
    def remove_queue(self):
        pass

    @abstractmethod
    def send_message(self, serialized_message: str):
        pass

    @abstractmethod
    def receive_message(self) -> str:
        pass