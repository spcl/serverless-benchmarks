"""Azure system resources management for SeBS.

This module provides Azure-specific system resource management including
storage accounts, CosmosDB instances, and Azure CLI management for
serverless benchmark execution.
"""

import json
from typing import Optional, cast

import docker

from sebs.azure.blob_storage import BlobStorage
from sebs.azure.cli import AzureCLI
from sebs.azure.config import AzureConfig
from sebs.azure.cosmosdb import CosmosDB
from sebs.cache import Cache
from sebs.config import SeBSConfig
from sebs.faas.resources import SystemResources
from sebs.utils import LoggingHandlers


class AzureSystemResources(SystemResources):
    """Azure system resources manager for SeBS benchmarking.

    Manages Azure-specific system resources including Blob Storage,
    CosmosDB for NoSQL operations, and Azure CLI for resource management.
    Handles authentication, resource initialization, and lifecycle management.

    Attributes:
        _logging_handlers (LoggingHandlers): Logging configuration handlers
        _storage (Optional[BlobStorage]): Azure Blob Storage instance
        _nosql_storage (Optional[CosmosDB]): Azure CosmosDB instance
        _cli_instance (Optional[AzureCLI]): Azure CLI Docker container instance
        _system_config (SeBSConfig): SeBS system configuration
        _cli_instance_stop (bool): Flag to control CLI instance lifecycle
    """

    @staticmethod
    def typename() -> str:
        """Get the system resources type name.

        Returns:
            str: Type identifier for Azure system resources.
        """
        return "Azure.SystemResources"

    @property
    def config(self) -> AzureConfig:
        """Get the Azure configuration.

        Returns:
            AzureConfig: Azure-specific configuration instance.
        """
        return cast(AzureConfig, self._config)

    def __init__(
        self,
        system_config: SeBSConfig,
        config: AzureConfig,
        cache_client: Cache,
        docker_client: docker.client.DockerClient,
        logger_handlers: LoggingHandlers,
    ) -> None:
        """Initialize Azure system resources.

        Args:
            system_config (SeBSConfig): SeBS system configuration
            config (AzureConfig): Azure-specific configuration
            cache_client (Cache): Cache for storing resource information
            docker_client (docker.client.DockerClient): Docker client for container management
            logger_handlers (LoggingHandlers): Logging configuration handlers
        """
        super().__init__(config, cache_client, docker_client)

        self._logging_handlers = logger_handlers
        self._storage: Optional[BlobStorage] = None
        self._nosql_storage: Optional[CosmosDB] = None
        self._cli_instance: Optional[AzureCLI] = None
        self._system_config = system_config
        self._cli_instance_stop: bool = True

    def get_storage(self, replace_existing: Optional[bool] = None) -> BlobStorage:
        """Get or create Azure Blob Storage instance.

        Requires Azure CLI instance in Docker to obtain storage account details.

        Args:
            replace_existing (Optional[bool]): When True, replace existing files in input buckets.
                If None, defaults to False.

        Returns:
            BlobStorage: Azure Blob Storage instance for benchmark data management.
        """
        if self._storage is None:
            self._storage = BlobStorage(
                self.config.region,
                self._cache_client,
                self.config.resources,
                self.config.resources.data_storage_account(self.cli_instance).connection_string,
                replace_existing=replace_existing if replace_existing is not None else False,
            )
            self._storage.logging_handlers = self.logging_handlers
        elif replace_existing is not None:
            self._storage.replace_existing = replace_existing
        return self._storage

    def get_nosql_storage(self) -> CosmosDB:
        """Get or create Azure CosmosDB instance.

        Creates and configures CosmosDB instance for NoSQL benchmark operations.
        Handles authentication and database/container creation as needed.

        Requires Azure CLI instance in Docker.

        Returns:
            CosmosDB: Azure CosmosDB instance for NoSQL operations.
        """
        if self._nosql_storage is None:
            self._nosql_storage = CosmosDB(
                self.cli_instance, self._cache_client, self.config.resources, self.config.region
            )
        return self._nosql_storage

    def _login_cli(self) -> None:
        """Login to Azure CLI using service principal credentials.

        Authenticates with Azure using the configured service principal
        credentials and validates subscription access.

        Raises:
            RuntimeError: If no valid subscription is found or multiple subscriptions exist.
            AssertionError: If CLI instance is not initialized.
        """
        assert self._cli_instance is not None

        output = self._cli_instance.login(
            appId=self.config.credentials.appId,
            tenant=self.config.credentials.tenant,
            password=self.config.credentials.password,
        )

        subscriptions = json.loads(output)
        if len(subscriptions) == 0:
            raise RuntimeError("Didn't find any valid subscription on Azure!")
        if len(subscriptions) > 1:
            raise RuntimeError("Found more than one valid subscription on Azure - not supported!")

        self.config.credentials.subscription_id = subscriptions[0]["id"]

    @property
    def cli_instance(self) -> AzureCLI:
        """Get or create Azure CLI instance.

        Creates and initializes Azure CLI Docker container if not already created.
        Handles authentication automatically on first access.

        Returns:
            AzureCLI: Azure CLI instance for executing Azure commands.
        """
        if self._cli_instance is None:
            self._cli_instance = AzureCLI(self._system_config, self._docker_client)
            self._cli_instance_stop = True

            self._login_cli()

        return self._cli_instance

    def initialize_cli(self, cli: AzureCLI, login: bool = False) -> None:
        """Initialize with existing Azure CLI instance.

        Allows using an external Azure CLI instance instead of creating a new one.
        Useful for sharing CLI instances across multiple resource managers.

        Args:
            cli (AzureCLI): External Azure CLI instance to use
            login (bool): Whether to perform login with this CLI instance.
                Defaults to False.
        """
        self._cli_instance = cli
        self._cli_instance_stop = False

        if login:
            self._login_cli()

    def shutdown(self) -> None:
        """Shutdown Azure system resources.

        Cleans up Azure CLI Docker container and other resources.
        Only shuts down CLI if it was created by this instance.
        Does not terminate CLI instance attached to the class.
        """
        if self._cli_instance and self._cli_instance_stop:
            self._cli_instance.shutdown()
