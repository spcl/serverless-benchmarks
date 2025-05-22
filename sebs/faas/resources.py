from abc import abstractmethod, ABC
from typing import Optional

import docker

from sebs.cache import Cache
from sebs.faas.config import Config
from sebs.faas.storage import PersistentStorage
from sebs.faas.nosql import NoSQLStorage
from sebs.utils import LoggingBase


class SystemResources(ABC, LoggingBase):
    """
    Abstract base class for managing system-level resources for a FaaS deployment.

    This includes access to persistent storage (like S3 or Azure Blob Storage)
    and NoSQL storage (like DynamoDB or CosmosDB). Implementations are specific
    to each FaaS provider.
    """
    def __init__(self, config: Config, cache_client: Cache, docker_client: docker.client):
        """
        Initialize SystemResources.

        :param config: The FaaS system configuration object.
        :param cache_client: The cache client instance.
        :param docker_client: The Docker client instance.
        """
        super().__init__()

        self._config = config
        self._cache_client = cache_client
        self._docker_client = docker_client

    @abstractmethod
    def get_storage(self, replace_existing: Optional[bool] = None) -> PersistentStorage:
        """
        Get an instance of the persistent storage client for the FaaS provider.

        This storage might be a remote service (e.g., AWS S3, Azure Blob Storage)
        or a local equivalent.

        :param replace_existing: If True, any existing benchmark input data in
                                 the storage should be replaced. Defaults to False.
        :return: An instance of a PersistentStorage subclass.
        """
        pass

    @abstractmethod
    def get_nosql_storage(self) -> NoSQLStorage:
        """
        Get an instance of the NoSQL storage client for the FaaS provider.

        This storage might be a remote service (e.g., AWS DynamoDB, Azure CosmosDB)
        or a local equivalent (e.g., a ScyllaDB container).

        :return: An instance of a NoSQLStorage subclass.
        """
        pass
