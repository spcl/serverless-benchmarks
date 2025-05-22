from typing import cast, Optional

from sebs.aws.s3 import S3
from sebs.aws.dynamodb import DynamoDB
from sebs.aws.config import AWSConfig
from sebs.cache import Cache
from sebs.faas.resources import SystemResources
from sebs.faas.storage import PersistentStorage
from sebs.faas.nosql import NoSQLStorage
from sebs.utils import LoggingHandlers

import boto3
import docker


class AWSSystemResources(SystemResources):
    """Manages system-level resources for AWS, such as S3 and DynamoDB clients."""
    @staticmethod
    def typename() -> str:
        """Return the type name of the system resources class."""
        return "AWS.SystemResources"

    @property
    def config(self) -> AWSConfig:
        """Return the AWS-specific configuration."""
        return cast(AWSConfig, self._config)

    def __init__(
        self,
        config: AWSConfig,
        cache_client: Cache,
        docker_client: docker.client,
        logger_handlers: LoggingHandlers,
    ):
        """
        Initialize AWSSystemResources.

        :param config: AWS-specific configuration.
        :param cache_client: Cache client instance.
        :param docker_client: Docker client instance.
        :param logger_handlers: Logging handlers.
        """
        super().__init__(config, cache_client, docker_client)

        self._session: Optional[boto3.session.Session] = None
        self._logging_handlers = logger_handlers
        self._storage: Optional[S3] = None
        self._nosql_storage: Optional[DynamoDB] = None

    def initialize_session(self, session: boto3.session.Session):
        """
        Initialize the Boto3 session for AWS clients.

        :param session: Boto3 session instance.
        """
        self._session = session

    def get_storage(self, replace_existing: Optional[bool] = None) -> PersistentStorage:
        """
        Get or initialize the S3 persistent storage client.

        Creates an S3 client instance if it doesn't exist. When benchmark and buckets
        parameters are passed (implicitly via config), storage is initialized with the
        required number of buckets. Buckets may be created or retrieved from cache.

        :param replace_existing: If True, replace existing files in cached buckets.
                                 Defaults to False if None.
        :return: S3 persistent storage client.
        """
        if not self._storage:
            assert self._session is not None
            self.logging.info("Initialize S3 storage instance.")
            self._storage = S3(
                self._session,
                self._cache_client,
                self.config.resources,
                self.config.region,
                access_key=self.config.credentials.access_key,
                secret_key=self.config.credentials.secret_key,
                replace_existing=replace_existing if replace_existing is not None else False,
            )
            self._storage.logging_handlers = self._logging_handlers
        elif replace_existing is not None:
            self._storage.replace_existing = replace_existing
        return self._storage

    def get_nosql_storage(self) -> NoSQLStorage:
        """
        Get or initialize the DynamoDB NoSQL storage client.

        Creates a DynamoDB client instance if it doesn't exist.

        :return: DynamoDB NoSQL storage client.
        """
        if not self._nosql_storage:
            assert self._session is not None
            self.logging.info("Initialize DynamoDB NoSQL instance.")
            self._nosql_storage = DynamoDB(
                self._session,
                self._cache_client,
                self.config.resources,
                self.config.region,
                access_key=self.config.credentials.access_key,
                secret_key=self.config.credentials.secret_key,
            )
        return self._nosql_storage
