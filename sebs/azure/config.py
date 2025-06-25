"""Configuration management for Azure serverless benchmarking.

This module provides configuration classes for Azure resources, credentials,
and deployment settings. It handles Azure-specific configuration including
service principal authentication, resource group management, storage accounts,
and CosmosDB setup for the SeBS benchmarking suite.

Key classes:
    AzureCredentials: Manages Azure service principal authentication
    AzureResources: Manages Azure resource allocation and lifecycle
    AzureConfig: Combines credentials and resources for Azure deployment

Example:
    Basic usage for setting up Azure configuration:

    ::

        from sebs.azure.config import AzureConfig, AzureCredentials, AzureResources
        from sebs.cache import Cache

        # Load configuration from config dict and cache
        config = AzureConfig.deserialize(config_dict, cache, handlers)
        credentials = config.credentials
        resources = config.resources
"""

import json
import logging
import os
import re
import uuid
from typing import cast, Dict, List, Optional

from sebs.azure.cli import AzureCLI
from sebs.azure.cloud_resources import CosmosDBAccount
from sebs.cache import Cache
from sebs.faas.config import Config, Credentials, Resources
from sebs.utils import LoggingHandlers


class AzureCredentials(Credentials):
    """Azure service principal credentials for authentication.

    This class manages Azure service principal credentials required for
    authenticating with Azure services. It handles app ID, tenant ID,
    password, and subscription ID validation and caching.

    Attributes:
        _appId: Azure application (client) ID
        _tenant: Azure tenant (directory) ID
        _password: Azure client secret
        _subscription_id: Azure subscription ID (optional)
    """

    _appId: str
    _tenant: str
    _password: str
    _subscription_id: Optional[str]

    def __init__(
        self, appId: str, tenant: str, password: str, subscription_id: Optional[str] = None
    ) -> None:
        """Initialize Azure credentials.

        Args:
            appId: Azure application (client) ID
            tenant: Azure tenant (directory) ID
            password: Azure client secret
            subscription_id: Azure subscription ID (optional)
        """
        super().__init__()
        self._appId = appId
        self._tenant = tenant
        self._password = password
        self._subscription_id = subscription_id

    @property
    def appId(self) -> str:
        """Get the Azure application (client) ID.

        Returns:
            Azure application ID string.
        """
        return self._appId

    @property
    def tenant(self) -> str:
        """Get the Azure tenant (directory) ID.

        Returns:
            Azure tenant ID string.
        """
        return self._tenant

    @property
    def password(self) -> str:
        """Get the Azure client secret.

        Returns:
            Azure client secret string.
        """
        return self._password

    @property
    def subscription_id(self) -> str:
        """Get the Azure subscription ID.

        Returns:
            Azure subscription ID string.

        Raises:
            AssertionError: If subscription ID is not set.
        """
        assert self._subscription_id is not None
        return self._subscription_id

    @subscription_id.setter
    def subscription_id(self, subscription_id: str) -> None:
        """Set the Azure subscription ID with validation.

        Args:
            subscription_id: Azure subscription ID to set

        Raises:
            RuntimeError: If provided subscription ID conflicts with cached value.
        """
        if self._subscription_id is not None and subscription_id != self._subscription_id:
            self.logging.error(
                f"The subscription id {subscription_id} from provided "
                f"credentials is different from the subscription id "
                f"{self._subscription_id} found in the cache! "
                "Please change your cache directory or create a new one!"
            )
            raise RuntimeError(
                f"Azure login credentials do not match the subscription "
                f"{self._subscription_id} in cache!"
            )

        self._subscription_id = subscription_id

    @property
    def has_subscription_id(self) -> bool:
        """Check if subscription ID is set.

        Returns:
            True if subscription ID is set, False otherwise.
        """
        return self._subscription_id is not None

    @staticmethod
    def initialize(dct: dict, subscription_id: Optional[str]) -> "AzureCredentials":
        """Initialize credentials from dictionary.

        Args:
            dct: Dictionary containing credential information
            subscription_id: Optional subscription ID to set

        Returns:
            New AzureCredentials instance.
        """
        return AzureCredentials(dct["appId"], dct["tenant"], dct["password"], subscription_id)

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Credentials:
        """Deserialize credentials from config and cache.

        Loads Azure credentials from either the configuration dictionary
        or environment variables, with subscription ID retrieved from cache.

        Args:
            config: Configuration dictionary
            cache: Cache instance for storing/retrieving cached values
            handlers: Logging handlers for error reporting

        Returns:
            AzureCredentials instance with loaded configuration.

        Raises:
            RuntimeError: If no valid credentials are found in config or environment.
        """
        cached_config = cache.get_config("azure")
        ret: AzureCredentials
        old_subscription_id: Optional[str] = None
        # Load cached values
        if cached_config and "credentials" in cached_config:
            old_subscription_id = cached_config["credentials"]["subscription_id"]

        # Check for new config
        if "credentials" in config and "appId" in config["credentials"]:
            ret = AzureCredentials.initialize(config["credentials"], old_subscription_id)
        elif "AZURE_SECRET_APPLICATION_ID" in os.environ:
            ret = AzureCredentials(
                os.environ["AZURE_SECRET_APPLICATION_ID"],
                os.environ["AZURE_SECRET_TENANT"],
                os.environ["AZURE_SECRET_PASSWORD"],
                old_subscription_id,
            )
        else:
            raise RuntimeError(
                "Azure login credentials are missing! Please set "
                "up environmental variables AZURE_SECRET_APPLICATION_ID and "
                "AZURE_SECRET_TENANT and AZURE_SECRET_PASSWORD"
            )
        ret.logging_handlers = handlers

        return ret

    def serialize(self) -> dict:
        """Serialize credentials to dictionary.

        Returns:
            Dictionary containing serialized credential data.
        """
        out = {"subscription_id": self.subscription_id}
        return out

    def update_cache(self, cache_client: Cache) -> None:
        """Update credentials in cache.

        Args:
            cache_client: Cache instance to update
        """
        cache_client.update_config(val=self.serialize(), keys=["azure", "credentials"])


class AzureResources(Resources):
    """Azure resource management for SeBS benchmarking.

    This class manages Azure cloud resources including storage accounts,
    resource groups, and CosmosDB accounts required for serverless function
    benchmarking. It handles resource allocation, caching, and lifecycle management.

    Attributes:
        _resource_group: Name of the Azure resource group
        _storage_accounts: List of storage accounts for function code
        _data_storage_account: Storage account for benchmark data
        _cosmosdb_account: CosmosDB account for NoSQL storage
    """

    class Storage:
        """Azure Storage Account wrapper.

        Represents an Azure Storage Account with connection details
        for use in serverless function deployment and data storage.

        Attributes:
            account_name: Name of the Azure storage account
            connection_string: Connection string for accessing the storage account
        """

        def __init__(self, account_name: str, connection_string: str) -> None:
            """Initialize Azure Storage account.

            Args:
                account_name: Name of the Azure storage account
                connection_string: Connection string for storage access
            """
            super().__init__()
            self.account_name = account_name
            self.connection_string = connection_string

        @staticmethod
        def from_cache(account_name: str, connection_string: str) -> "AzureResources.Storage":
            """Create Storage instance from cached data.

            Args:
                account_name: Name of the storage account
                connection_string: Connection string for the account

            Returns:
                New Storage instance with the provided details.

            Raises:
                AssertionError: If connection string is empty.
            """
            assert connection_string, "Empty connection string for account {}".format(account_name)
            return AzureResources.Storage(account_name, connection_string)

        @staticmethod
        def from_allocation(account_name: str, cli_instance: AzureCLI) -> "AzureResources.Storage":
            """Create Storage instance from newly allocated account.

            Args:
                account_name: Name of the storage account
                cli_instance: Azure CLI instance for querying connection string

            Returns:
                New Storage instance with queried connection string.
            """
            connection_string = AzureResources.Storage.query_connection_string(
                account_name, cli_instance
            )
            ret = AzureResources.Storage(account_name, connection_string)
            return ret

        @staticmethod
        def query_connection_string(account_name: str, cli_instance: AzureCLI) -> str:
            """Query connection string for storage account from Azure.

            Args:
                account_name: Name of the storage account
                cli_instance: Azure CLI instance for executing queries

            Returns:
                Connection string for the storage account.
            """
            ret = cli_instance.execute(
                "az storage account show-connection-string --name {}".format(account_name)
            )
            ret_dct = json.loads(ret.decode("utf-8"))
            connection_string = ret_dct["connectionString"]
            return connection_string

        def serialize(self) -> dict:
            """Serialize storage account to dictionary.

            Returns:
                Dictionary containing storage account information.
            """
            return vars(self)

        @staticmethod
        def deserialize(obj: dict) -> "AzureResources.Storage":
            """Deserialize storage account from dictionary.

            Args:
                obj: Dictionary containing storage account data

            Returns:
                New Storage instance from dictionary data.
            """
            return AzureResources.Storage.from_cache(obj["account_name"], obj["connection_string"])

    def __init__(
        self,
        resource_group: Optional[str] = None,
        storage_accounts: Optional[List["AzureResources.Storage"]] = None,
        data_storage_account: Optional["AzureResources.Storage"] = None,
        cosmosdb_account: Optional[CosmosDBAccount] = None,
    ) -> None:
        """Initialize Azure resources.

        Args:
            resource_group: Name of Azure resource group
            storage_accounts: List of storage accounts for function code
            data_storage_account: Storage account for benchmark data
            cosmosdb_account: CosmosDB account for NoSQL operations
        """
        super().__init__(name="azure")
        self._resource_group = resource_group
        self._storage_accounts = storage_accounts or []
        self._data_storage_account = data_storage_account
        self._cosmosdb_account = cosmosdb_account

    def set_region(self, region: str) -> None:
        """Set the Azure region for resource allocation.

        Args:
            region: Azure region name (e.g., 'westus2')
        """
        self._region = region

    @property
    def storage_accounts(self) -> List["AzureResources.Storage"]:
        """Get list of storage accounts for function code.

        Returns:
            List of Storage instances for function deployment.
        """
        return self._storage_accounts

    def resource_group(self, cli_instance: AzureCLI) -> str:
        """Get or create Azure resource group.

        Locates existing resource group or creates a new one with UUID-based name.
        The resource group is used to contain all SeBS-related Azure resources.

        Args:
            cli_instance: Azure CLI instance for resource operations

        Returns:
            Name of the resource group.
        """
        # Create resource group if not known
        if not self._resource_group:
            # Only underscore and alphanumeric characters are allowed
            self._resource_group = "sebs_resource_group_{}".format(self.resources_id)

            groups = self.list_resource_groups(cli_instance)
            if self._resource_group in groups:
                self.logging.info("Using existing resource group {}.".format(self._resource_group))
            else:
                self.logging.info(
                    "Starting allocation of resource group {}.".format(self._resource_group)
                )
                cli_instance.execute(
                    "az group create --name {0} --location {1}".format(
                        self._resource_group, self._region
                    )
                )
                self.logging.info("Resource group {} created.".format(self._resource_group))
        return self._resource_group

    def list_resource_groups(self, cli_instance: AzureCLI) -> List[str]:
        """List SeBS resource groups in the current region.

        Queries Azure for existing resource groups that match the SeBS naming pattern.

        Args:
            cli_instance: Azure CLI instance for executing queries

        Returns:
            List of resource group names matching SeBS pattern.

        Raises:
            RuntimeError: If Azure CLI response cannot be parsed.
        """
        ret = cli_instance.execute(
            "az group list --query "
            "\"[?starts_with(name,'sebs_resource_group_') && location=='{0}']\"".format(
                self._region
            )
        )
        try:
            resource_groups = json.loads(ret.decode())
            return [x["name"] for x in resource_groups]
        except Exception:
            self.logging.error("Failed to parse the response!")
            self.logging.error(ret.decode())
            raise RuntimeError("Failed to parse response from Azure CLI!")

    def delete_resource_group(self, cli_instance: AzureCLI, name: str, wait: bool = True) -> None:
        """Delete Azure resource group.

        Removes the specified resource group and all contained resources.

        Args:
            cli_instance: Azure CLI instance for executing deletion
            name: Name of resource group to delete
            wait: Whether to wait for deletion to complete

        Raises:
            RuntimeError: If resource group deletion fails.
        """
        cmd = "az group delete -y --name {0}".format(name)
        if not wait:
            cmd += " --no-wait"
        ret = cli_instance.execute(cmd)
        if len(ret) != 0:
            self.logging.error("Failed to delete the resource group!")
            self.logging.error(ret.decode())
            raise RuntimeError("Failed to delete the resource group!")

    def cosmosdb_account(self, cli_instance: AzureCLI) -> CosmosDBAccount:
        """Get or create CosmosDB account for NoSQL storage.

        Finds existing CosmosDB account or creates a new serverless one.
        Account names must be globally unique across Azure.

        Args:
            cli_instance: Azure CLI instance for CosmosDB operations

        Returns:
            CosmosDBAccount instance for NoSQL operations.

        Raises:
            RuntimeError: If CosmosDB account creation or parsing fails.
        """
        # Create resource group if not known
        if not self._cosmosdb_account:

            # Only hyphen and alphanumeric characters are allowed
            account_name = f"sebs-cosmosdb-account-{self.resources_id}"
            account_name = account_name.replace("_", "-")
            account_name = account_name.replace(".", "-")

            accounts = self.list_cosmosdb_accounts(cli_instance)
            if account_name in accounts:

                self.logging.info("Using existing CosmosDB account {}.".format(account_name))
                url = accounts[account_name]

            else:

                try:
                    self.logging.info(f"Starting allocation of CosmosDB account {account_name}")
                    self.logging.info("This can take few minutes :-)!")
                    ret = cli_instance.execute(
                        f" az cosmosdb create --name {account_name} "
                        f" --resource-group {self._resource_group} "
                        f' --locations regionName="{self._region}" '
                        " --capabilities EnableServerless "
                    )
                    ret_values = json.loads(ret.decode())
                    url = ret_values["documentEndpoint"]
                    self.logging.info(f"Allocated CosmosDB account {account_name}")
                except Exception:
                    self.logging.error("Failed to parse the response!")
                    self.logging.error(ret.decode())
                    raise RuntimeError("Failed to parse response from Azure CLI!")

            self._cosmosdb_account = CosmosDBAccount.from_allocation(
                account_name, self.resource_group(cli_instance), cli_instance, url
            )

        return self._cosmosdb_account

    def list_cosmosdb_accounts(self, cli_instance: AzureCLI) -> Dict[str, str]:
        """List existing CosmosDB accounts in resource group.

        Queries for CosmosDB accounts matching the SeBS naming pattern.

        Args:
            cli_instance: Azure CLI instance for executing queries

        Returns:
            Dictionary mapping account names to document endpoints.

        Raises:
            RuntimeError: If Azure CLI response cannot be parsed.
        """
        ret = cli_instance.execute(
            f" az cosmosdb list --resource-group {self._resource_group} "
            " --query \"[?starts_with(name,'sebs-cosmosdb-account')]\" "
        )
        try:
            accounts = json.loads(ret.decode())
            return {x["name"]: x["documentEndpoint"] for x in accounts}
        except Exception:
            self.logging.error("Failed to parse the response!")
            self.logging.error(ret.decode())
            raise RuntimeError("Failed to parse response from Azure CLI!")

    def data_storage_account(self, cli_instance: AzureCLI) -> "AzureResources.Storage":
        """Get or create storage account for benchmark data.

        Retrieves existing or creates new storage account dedicated to storing
        benchmark input/output data. This is separate from function code storage.

        Args:
            cli_instance: Azure CLI instance for storage operations

        Returns:
            Storage instance for benchmark data operations.
        """
        if not self._data_storage_account:

            # remove non-numerical and non-alphabetic characters
            parsed = re.compile("[^a-zA-Z0-9]").sub("", self.resources_id)

            account_name = "storage{}".format(parsed)
            self._data_storage_account = self._create_storage_account(cli_instance, account_name)
        return self._data_storage_account

    def list_storage_accounts(self, cli_instance: AzureCLI) -> List[str]:
        """List storage accounts in the resource group.

        Queries for all storage accounts within the managed resource group.

        Args:
            cli_instance: Azure CLI instance for executing queries

        Returns:
            List of storage account names.

        Raises:
            RuntimeError: If Azure CLI response cannot be parsed.
        """
        ret = cli_instance.execute(
            ("az storage account list --resource-group {0}").format(
                self.resource_group(cli_instance)
            )
        )
        try:
            storage_accounts = json.loads(ret.decode())
            return [x["name"] for x in storage_accounts]
        except Exception:
            self.logging.error("Failed to parse the response!")
            self.logging.error(ret.decode())
            raise RuntimeError("Failed to parse response from Azure CLI!")

    def add_storage_account(self, cli_instance: AzureCLI) -> "AzureResources.Storage":
        """Create new storage account for function code.

        Creates a new storage account with a UUID-based name for storing
        function code packages and adds it to the managed accounts list.

        Args:
            cli_instance: Azure CLI instance for storage operations

        Returns:
            New Storage instance for function code storage.
        """

        # Create account. Only alphanumeric characters are allowed
        # This one is used to store functions code - hence the name.
        uuid_name = str(uuid.uuid1())[0:8]
        account_name = "function{}".format(uuid_name)

        account = self._create_storage_account(cli_instance, account_name)
        self._storage_accounts.append(account)
        return account

    def _create_storage_account(
        self, cli_instance: AzureCLI, account_name: str
    ) -> "AzureResources.Storage":
        """Internal method to create storage account.

        Creates a new Azure storage account with the specified name.
        This method does NOT update cache or add to resource collections.

        Args:
            cli_instance: Azure CLI instance for storage operations
            account_name: Name for the new storage account

        Returns:
            New Storage instance for the created account.
        """
        sku = "Standard_LRS"
        self.logging.info("Starting allocation of storage account {}.".format(account_name))
        cli_instance.execute(
            (
                "az storage account create --name {0} --location {1} "
                "--resource-group {2} --sku {3}"
            ).format(
                account_name,
                self._region,
                self.resource_group(cli_instance),
                sku,
            )
        )
        self.logging.info("Storage account {} created.".format(account_name))
        return AzureResources.Storage.from_allocation(account_name, cli_instance)

    def update_cache(self, cache_client: Cache) -> None:
        """Update resource configuration in cache.

        Persists current resource state including storage accounts,
        data storage accounts, and resource groups to filesystem cache.

        Args:
            cache_client: Cache instance for storing configuration
        """
        super().update_cache(cache_client)
        cache_client.update_config(val=self.serialize(), keys=["azure", "resources"])

    @staticmethod
    def initialize(res: Resources, dct: dict) -> None:
        """Initialize resources from dictionary data.

        Populates resource instance with data from configuration dictionary.

        Args:
            res: Resources instance to initialize
            dct: Dictionary containing resource configuration
        """
        ret = cast(AzureResources, res)
        super(AzureResources, AzureResources).initialize(ret, dct)

        ret._resource_group = dct["resource_group"]
        if "storage_accounts" in dct:
            ret._storage_accounts = [
                AzureResources.Storage.deserialize(x) for x in dct["storage_accounts"]
            ]
        else:
            ret._storage_accounts = []

        if "data_storage_account" in dct:
            ret._data_storage_account = AzureResources.Storage.deserialize(
                dct["data_storage_account"]
            )

        if "cosmosdb_account" in dct:
            ret._cosmosdb_account = CosmosDBAccount.deserialize(dct["cosmosdb_account"])

    def serialize(self) -> dict:
        """Serialize resources to dictionary.

        Returns:
            Dictionary containing all resource configuration data.
        """
        out = super().serialize()
        if len(self._storage_accounts) > 0:
            out["storage_accounts"] = [x.serialize() for x in self._storage_accounts]
        if self._resource_group:
            out["resource_group"] = self._resource_group
        if self._cosmosdb_account:
            out["cosmosdb_account"] = self._cosmosdb_account.serialize()
        if self._data_storage_account:
            out["data_storage_account"] = self._data_storage_account.serialize()
        return out

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Resources:
        """Deserialize resources from config and cache.

        Loads Azure resources from cache if available, otherwise from configuration.

        Args:
            config: Configuration dictionary
            cache: Cache instance for retrieving cached values
            handlers: Logging handlers for error reporting

        Returns:
            AzureResources instance with loaded configuration.
        """
        cached_config = cache.get_config("azure")
        ret = AzureResources()
        # Load cached values
        if cached_config and "resources" in cached_config and len(cached_config["resources"]) > 0:
            logging.info("Using cached resources for Azure")
            AzureResources.initialize(ret, cached_config["resources"])
        else:
            # Check for new config
            if "resources" in config:
                AzureResources.initialize(ret, config["resources"])
                ret.logging_handlers = handlers
                ret.logging.info("No cached resources for Azure found, using user configuration.")
            else:
                ret = AzureResources()
                ret.logging_handlers = handlers
                ret.logging.info("No resources for Azure found, initialize!")
        return ret


class AzureConfig(Config):
    """Complete Azure configuration for SeBS benchmarking.

    Combines Azure credentials and resources into a single configuration
    object for managing Azure serverless function deployments.

    Attributes:
        _credentials: Azure service principal credentials
        _resources: Azure resource management instance
    """

    def __init__(self, credentials: AzureCredentials, resources: AzureResources) -> None:
        """Initialize Azure configuration.

        Args:
            credentials: Azure service principal credentials
            resources: Azure resource management instance
        """
        super().__init__(name="azure")
        self._credentials = credentials
        self._resources = resources

    @property
    def credentials(self) -> AzureCredentials:
        """Get Azure credentials.

        Returns:
            AzureCredentials instance for authentication.
        """
        return self._credentials

    @property
    def resources(self) -> AzureResources:
        """Get Azure resources manager.

        Returns:
            AzureResources instance for resource management.
        """
        return self._resources

    @staticmethod
    def initialize(cfg: Config, dct: dict) -> None:
        """Initialize configuration from dictionary data.

        Args:
            cfg: Config instance to initialize
            dct: Dictionary containing configuration data
        """
        config = cast(AzureConfig, cfg)
        config._region = dct["region"]

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Config:
        """Deserialize complete Azure configuration.

        Creates AzureConfig instance from configuration dictionary and cache,
        combining credentials and resources with region information.

        Args:
            config: Configuration dictionary
            cache: Cache instance for storing/retrieving cached values
            handlers: Logging handlers for error reporting

        Returns:
            AzureConfig instance with complete Azure configuration.
        """
        cached_config = cache.get_config("azure")
        credentials = cast(AzureCredentials, AzureCredentials.deserialize(config, cache, handlers))
        resources = cast(AzureResources, AzureResources.deserialize(config, cache, handlers))
        config_obj = AzureConfig(credentials, resources)
        config_obj.logging_handlers = handlers
        # Load cached values
        if cached_config:
            config_obj.logging.info("Using cached config for Azure")
            AzureConfig.initialize(config_obj, cached_config)
        else:
            config_obj.logging.info("Using user-provided config for Azure")
            AzureConfig.initialize(config_obj, config)

        resources.set_region(config_obj.region)
        return config_obj

    def update_cache(self, cache: Cache) -> None:
        """Update complete configuration in cache.

        Persists region, credentials, and resources to filesystem cache.

        Args:
            cache: Cache instance for storing configuration
        """
        cache.update_config(val=self.region, keys=["azure", "region"])
        self.credentials.update_cache(cache)
        self.resources.update_cache(cache)

    def serialize(self) -> dict:
        """Serialize complete configuration to dictionary.

        Returns:
            Dictionary containing all Azure configuration data.
        """
        out = {
            "name": "azure",
            "region": self._region,
            "credentials": self._credentials.serialize(),
            "resources": self._resources.serialize(),
        }
        return out
