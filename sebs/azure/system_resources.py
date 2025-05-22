import json
from typing import cast, Optional

from sebs.config import SeBSConfig
from sebs.azure.config import AzureConfig
from sebs.azure.blob_storage import BlobStorage
from sebs.azure.cosmosdb import CosmosDB
from sebs.azure.cli import AzureCLI
from sebs.cache import Cache
from sebs.faas.resources import SystemResources
from sebs.utils import LoggingHandlers

import docker


class AzureSystemResources(SystemResources):
    """Manages system-level resources for Azure, such as Blob Storage, CosmosDB, and Azure CLI."""
    @staticmethod
    def typename() -> str:
        """Return the type name of the system resources class."""
        return "Azure.SystemResources"

    @property
    def config(self) -> AzureConfig:
        """Return the Azure-specific configuration."""
        return cast(AzureConfig, self._config)

    def __init__(
        self,
        system_config: SeBSConfig,
        config: AzureConfig,
        cache_client: Cache,
        docker_client: docker.client,
        logger_handlers: LoggingHandlers,
    ):
        """
        Initialize AzureSystemResources.

        :param system_config: SeBS system configuration.
        :param config: Azure-specific configuration.
        :param cache_client: Cache client instance.
        :param docker_client: Docker client instance.
        :param logger_handlers: Logging handlers.
        """
        super().__init__(config, cache_client, docker_client)

        self._logging_handlers = logger_handlers
        self._storage: Optional[BlobStorage] = None
        self._nosql_storage: Optional[CosmosDB] = None
        self._cli_instance: Optional[AzureCLI] = None
        self._system_config = system_config

    def get_storage(self, replace_existing: Optional[bool] = None) -> BlobStorage:
        """
        Get or initialize the Azure Blob Storage client.

        Ensures that the data storage account is created and its connection string
        is known. Creates the BlobStorage wrapper instance.

        Requires Azure CLI instance to obtain storage account details if not cached.

        :param replace_existing: If True, replace existing files in input buckets.
                                 Defaults to False if None.
        :return: BlobStorage instance.
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
        """
        Get or initialize the Azure CosmosDB client.

        Creates a CosmosDB wrapper instance. Requires Azure CLI for initial setup
        if resources are not cached.

        :return: CosmosDB instance.
        """
        if self._nosql_storage is None:
            self._nosql_storage = CosmosDB(
                self.cli_instance, self._cache_client, self.config.resources, self.config.region
            )
        return self._nosql_storage

    def _login_cli(self):
        """
        Log in to Azure CLI using service principal credentials.

        Retrieves appId, tenant, and password from the configuration.
        Sets the subscription ID in the credentials after successful login.

        :raises RuntimeError: If no valid subscription is found or if multiple are found.
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
        """
        Get or initialize the Azure CLI wrapper instance.

        If the CLI instance doesn't exist, it's created, and a login is performed.
        This instance will be stopped on shutdown.

        :return: AzureCLI instance.
        """
        if self._cli_instance is None:
            self._cli_instance = AzureCLI(self._system_config, self._docker_client)
            self._cli_instance_stop = True  # Mark that this instance owns the CLI lifecycle

            self._login_cli()

        return self._cli_instance

    def initialize_cli(self, cli: AzureCLI, login: bool = False):
        """
        Initialize with an externally managed Azure CLI instance.

        This allows sharing a single AzureCLI Docker container across multiple
        SeBS instances or components. The provided CLI instance will not be
        stopped on shutdown by this AzureSystemResources instance.

        :param cli: An existing AzureCLI instance.
        :param login: If True, perform Azure login using this instance's credentials.
        """
        self._cli_instance = cli
        self._cli_instance_stop = False  # Mark that this instance does not own the CLI lifecycle

        if login:
            self._login_cli()

    def shutdown(self) -> None:
        """
        Shutdown the Azure system resources.

        Stops the Azure CLI Docker container if it was started and is managed by
        this instance.
        """
        if self._cli_instance and self._cli_instance_stop:
            self._cli_instance.shutdown()
