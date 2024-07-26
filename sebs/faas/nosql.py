from abc import ABC
from abc import abstractmethod

from sebs.faas.config import Resources
from sebs.cache import Cache
from sebs.utils import LoggingBase


class NoSQLStorage(ABC, LoggingBase):
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

    def __init__(self, region: str, cache_client: Cache, resources: Resources):
        super().__init__()
        self._cache_client = cache_client
        self._cached = False
        self._region = region
        self._cloud_resources = resources

    """

        AWS: DynamoDB Table
        Azure: CosmosDB Container
        Google Cloud: Firestore in Datastore Mode, Database

    """

    @abstractmethod
    def create_table(self, name: str) -> str:
        pass

    """

        AWS DynamoDB: Removing & recreating table is the cheapest & fastest option


        Azure CosmosDB: recreate container

        Google Cloud: also likely recreate

    """

    @abstractmethod
    def clear_table(self, name: str) -> str:
        pass

    @abstractmethod
    def remove_table(self, name: str) -> str:
        pass
