"""AWS system resources management for SeBS.

This module provides the AWSSystemResources class which manages AWS-specific
resources like S3 storage and DynamoDB NoSQL storage within the SeBS framework.
It handles initialization, caching, and provides access to AWS services.

Key classes:
    AWSSystemResources: Main resource manager for AWS services
"""

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
    """AWS system resources manager for SeBS.

    This class manages AWS-specific resources including S3 storage and DynamoDB
    NoSQL storage. It provides a unified interface for accessing AWS services
    with proper session management and caching.

    Attributes:
        _session: AWS boto3 session for API calls
        _logging_handlers: Logging configuration handlers
        _storage: S3 storage client instance
        _nosql_storage: DynamoDB NoSQL storage client instance
    """

    @staticmethod
    def typename() -> str:
        """Get the type name for these resources.

        Returns:
            str: The type name 'AWS.SystemResources'
        """
        return "AWS.SystemResources"

    @property
    def config(self) -> AWSConfig:
        """Get the AWS configuration.

        Returns:
            AWSConfig: AWS-specific configuration
        """
        return cast(AWSConfig, self._config)

    def __init__(
        self,
        config: AWSConfig,
        cache_client: Cache,
        docker_client: docker.client,
        logger_handlers: LoggingHandlers,
    ) -> None:
        """Initialize AWS system resources.

        Args:
            config: AWS-specific configuration
            cache_client: Cache client for resource caching
            docker_client: Docker client for container operations
            logger_handlers: Logging configuration handlers
        """
        super().__init__(config, cache_client, docker_client)

        self._session: Optional[boto3.session.Session] = None
        self._logging_handlers = logger_handlers
        self._storage: Optional[S3] = None
        self._nosql_storage: Optional[DynamoDB] = None

    def initialize_session(self, session: boto3.session.Session) -> None:
        """Initialize the AWS boto3 session.

        Args:
            session: Boto3 session to use for AWS API calls
        """
        self._session = session

    def get_storage(self, replace_existing: Optional[bool] = None) -> PersistentStorage:
        """Get or create S3 storage client.

        Creates a client instance for S3 cloud storage. Storage is initialized
        with required buckets that may be created or retrieved from cache.

        Args:
            replace_existing: Whether to replace existing files in cached buckets

        Returns:
            PersistentStorage: S3 storage client instance

        Raises:
            AssertionError: If session has not been initialized
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
        """Get or create DynamoDB NoSQL storage client.

        Creates a client instance for DynamoDB NoSQL storage. The client
        is configured with AWS credentials and region from the system config.

        Returns:
            NoSQLStorage: DynamoDB NoSQL storage client instance

        Raises:
            AssertionError: If session has not been initialized
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
