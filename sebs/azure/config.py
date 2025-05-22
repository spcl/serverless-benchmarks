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
    """Azure service principal credentials."""
    _appId: str
    _tenant: str
    _password: str

    def __init__(
        self, appId: str, tenant: str, password: str, subscription_id: Optional[str] = None
    ):
        """
        Initialize Azure credentials.

        :param appId: Application ID of the service principal.
        :param tenant: Tenant ID.
        :param password: Password/secret of the service principal.
        :param subscription_id: Optional Azure subscription ID.
        """
        super().__init__()
        self._appId = appId
        self._tenant = tenant
        self._password = password
        self._subscription_id = subscription_id

    @property
    def appId(self) -> str:
        """Application ID of the service principal."""
        return self._appId

    @property
    def tenant(self) -> str:
        """Tenant ID."""
        return self._tenant

    @property
    def password(self) -> str:
        """Password/secret of the service principal."""
        return self._password

    @property
    def subscription_id(self) -> str:
        """Azure subscription ID."""
        assert self._subscription_id is not None
        return self._subscription_id

    @subscription_id.setter
    def subscription_id(self, subscription_id: str):
        """
        Set the Azure subscription ID.

        Logs an error and raises RuntimeError if the new subscription ID
        conflicts with an existing one from the cache.

        :param subscription_id: The Azure subscription ID.
        :raises RuntimeError: If the new subscription ID conflicts with a cached one.
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
        """Check if the subscription ID has been set."""
        return self._subscription_id is not None

    @staticmethod
    def initialize(dct: dict, subscription_id: Optional[str]) -> "AzureCredentials":
        """
        Initialize AzureCredentials from a dictionary.

        :param dct: Dictionary containing 'appId', 'tenant', and 'password'.
        :param subscription_id: Optional Azure subscription ID.
        :return: AzureCredentials instance.
        """
        return AzureCredentials(dct["appId"], dct["tenant"], dct["password"], subscription_id)

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Credentials:
        """
        Deserialize Azure credentials from configuration or environment variables.

        Prioritizes credentials from the config dictionary, then environment variables.
        Uses cached subscription ID if available.

        :param config: Configuration dictionary.
        :param cache: Cache object for retrieving cached subscription ID.
        :param handlers: Logging handlers.
        :return: AzureCredentials instance.
        :raises RuntimeError: If credentials are not found.
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
        """
        Serialize Azure credentials to a dictionary.

        :return: Dictionary containing the subscription ID.
        """
        out = {"subscription_id": self.subscription_id}
        return out

    def update_cache(self, cache_client: Cache):
        """
        Update the cache with the serialized Azure credentials.

        :param cache_client: Cache client instance.
        """
        cache_client.update_config(val=self.serialize(), keys=["azure", "credentials"])


class AzureResources(Resources):
    """Manages Azure resources like resource groups, storage accounts, and CosmosDB accounts."""
    class Storage:
        """Represents an Azure Storage account with its name and connection string."""
        def __init__(self, account_name: str, connection_string: str):
            """
            Initialize an Azure Storage account representation.

            :param account_name: Name of the storage account.
            :param connection_string: Connection string for the storage account.
            """
            super().__init__()
            self.account_name = account_name
            self.connection_string = connection_string

        # FIXME: 3.7+ migration with future annotations
        @staticmethod
        def from_cache(account_name: str, connection_string: str) -> "AzureResources.Storage":
            """
            Create an AzureResources.Storage instance from cached values.

            :param account_name: Name of the storage account.
            :param connection_string: Connection string.
            :return: AzureResources.Storage instance.
            """
            assert connection_string, "Empty connection string for account {}".format(account_name)
            return AzureResources.Storage(account_name, connection_string)

        @staticmethod
        def from_allocation(account_name: str, cli_instance: AzureCLI) -> "AzureResources.Storage":
            """
            Create an AzureResources.Storage instance by querying its connection string.

            :param account_name: Name of the storage account.
            :param cli_instance: AzureCLI instance.
            :return: AzureResources.Storage instance.
            """
            connection_string = AzureResources.Storage.query_connection_string(
                account_name, cli_instance
            )
            ret = AzureResources.Storage(account_name, connection_string)
            return ret

        @staticmethod
        def query_connection_string(account_name: str, cli_instance: AzureCLI) -> str:
            """
            Query the connection string for an Azure Storage account.

            :param account_name: Name of the storage account.
            :param cli_instance: AzureCLI instance.
            :return: Connection string.
            """
            ret = cli_instance.execute(
                "az storage account show-connection-string --name {}".format(account_name)
            )
            ret = json.loads(ret.decode("utf-8"))
            connection_string = ret["connectionString"]
            return connection_string

        def serialize(self) -> dict:
            """
            Serialize the Storage instance to a dictionary.

            :return: Dictionary representation of the Storage instance.
            """
            return vars(self)

        @staticmethod
        def deserialize(obj: dict) -> "AzureResources.Storage":
            """
            Deserialize an AzureResources.Storage instance from a dictionary.

            :param obj: Dictionary representation.
            :return: AzureResources.Storage instance.
            """
            return AzureResources.Storage.from_cache(obj["account_name"], obj["connection_string"])

    # FIXME: 3.7 Python, future annotations
    def __init__(
        self,
        resource_group: Optional[str] = None,
        storage_accounts: List["AzureResources.Storage"] = [],
        data_storage_account: Optional["AzureResources.Storage"] = None,
        cosmosdb_account: Optional[CosmosDBAccount] = None,
    ):
        """
        Initialize AzureResources.

        :param resource_group: Optional name of the resource group.
        :param storage_accounts: List of function storage accounts.
        :param data_storage_account: Storage account for benchmark data.
        :param cosmosdb_account: CosmosDB account for NoSQL benchmarks.
        """
        super().__init__(name="azure")
        self._resource_group = resource_group
        self._storage_accounts = storage_accounts
        self._data_storage_account = data_storage_account
        self._cosmosdb_account = cosmosdb_account

    def set_region(self, region: str):
        """
        Set the Azure region for these resources.

        :param region: Azure region name (e.g., "westeurope").
        """
        self._region = region

    @property
    def storage_accounts(self) -> List["AzureResources.Storage"]:
        """List of Azure Storage accounts used for function code deployment."""
        return self._storage_accounts

    def resource_group(self, cli_instance: AzureCLI) -> str:
        """
        Get or create the Azure Resource Group for SeBS.

        If a resource group name is not already set, it generates one based on
        the resource ID and creates it in the configured region if it doesn't exist.

        Requires Azure CLI instance in Docker.

        :param cli_instance: AzureCLI instance.
        :return: Name of the resource group.
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
        """
        List SeBS-related resource groups in the configured region.

        Filters groups starting with "sebs_resource_group_".

        :param cli_instance: AzureCLI instance.
        :return: List of resource group names.
        :raises RuntimeError: If parsing the Azure CLI response fails.
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

    def delete_resource_group(self, cli_instance: AzureCLI, name: str, wait: bool = True):
        """
        Delete an Azure Resource Group.

        :param cli_instance: AzureCLI instance.
        :param name: Name of the resource group to delete.
        :param wait: If True, wait for the deletion to complete.
        :raises RuntimeError: If deletion fails.
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
        """
        Get or create a serverless Azure CosmosDB account.

        If an account name is not already set, it generates one based on the
        resource ID (globally unique) and creates it if it doesn't exist.

        Requires Azure CLI instance in Docker.

        :param cli_instance: AzureCLI instance.
        :return: CosmosDBAccount instance.
        :raises RuntimeError: If CosmosDB account creation or query fails.
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
                    self.logging.error(ret.decode()) # type: ignore
                    raise RuntimeError("Failed to parse response from Azure CLI!")

            self._cosmosdb_account = CosmosDBAccount.from_allocation(
                account_name, self.resource_group(cli_instance), cli_instance, url
            )

        return self._cosmosdb_account

    def list_cosmosdb_accounts(self, cli_instance: AzureCLI) -> Dict[str, str]:
        """
        List SeBS-related CosmosDB accounts in the current resource group.

        Filters accounts starting with "sebs-cosmosdb-account".

        :param cli_instance: AzureCLI instance.
        :return: Dictionary mapping account names to their document endpoint URLs.
        :raises RuntimeError: If parsing the Azure CLI response fails.
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
        """
        Retrieve or create the Azure Storage account for benchmark input/output data.

        The account name is derived from the resource ID.

        :param cli_instance: AzureCLI instance.
        :return: AzureResources.Storage instance for the data storage account.
        """
        if not self._data_storage_account:

            # remove non-numerical and non-alphabetic characters
            parsed = re.compile("[^a-zA-Z0-9]").sub("", self.resources_id)

            account_name = "storage{}".format(parsed)
            self._data_storage_account = self._create_storage_account(cli_instance, account_name)
        return self._data_storage_account

    def list_storage_accounts(self, cli_instance: AzureCLI) -> List[str]:
        """
        List all storage accounts in the current resource group.

        :param cli_instance: AzureCLI instance.
        :return: List of storage account names.
        :raises RuntimeError: If parsing the Azure CLI response fails.
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
        """
        Create a new Azure Storage account for function code and add it to the list.

        The account name is generated with a UUID to ensure uniqueness.

        :param cli_instance: AzureCLI instance.
        :return: AzureResources.Storage instance for the new function storage account.
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
        """
        Internal implementation of creating a new Azure Storage account.

        Uses Standard_LRS SKU. This method does NOT update the cache or
        add the account to any resource collection by itself.

        :param cli_instance: AzureCLI instance.
        :param account_name: Desired name for the storage account.
        :return: AzureResources.Storage instance for the created account.
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

    def update_cache(self, cache_client: Cache):
        """
        Update the user cache with Azure resource details.

        Saves storage accounts, data storage account, resource group,
        and CosmosDB account configurations.
        The changes are directly written to the file system.

        :param cache_client: Cache client instance.
        """
        super().update_cache(cache_client)
        cache_client.update_config(val=self.serialize(), keys=["azure", "resources"])

    @staticmethod
    def initialize(res: Resources, dct: dict):
        """
        Initialize AzureResources from a dictionary (typically from cache or config file).

        :param res: Resources object to initialize (cast to AzureResources).
        :param dct: Dictionary containing resource configurations.
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
        """
        Serialize AzureResources to a dictionary.

        :return: Dictionary representation of AzureResources.
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
        """
        Deserialize AzureResources from configuration or cache.

        Prioritizes cached configuration if available.

        :param config: Configuration dictionary.
        :param cache: Cache object.
        :param handlers: Logging handlers.
        :return: AzureResources instance.
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
    """Azure specific configuration, including credentials and resources."""
    def __init__(self, credentials: AzureCredentials, resources: AzureResources):
        """
        Initialize AzureConfig.

        :param credentials: AzureCredentials instance.
        :param resources: AzureResources instance.
        """
        super().__init__(name="azure")
        self._credentials = credentials
        self._resources = resources

    @property
    def credentials(self) -> AzureCredentials:
        """Return the Azure credentials."""
        return self._credentials

    @property
    def resources(self) -> AzureResources:
        """Return the Azure resources configuration."""
        return self._resources

    # FIXME: use future annotations (see sebs/faas/system)
    @staticmethod
    def initialize(cfg: Config, dct: dict):
        """
        Initialize AzureConfig attributes from a dictionary.

        Sets the Azure region.

        :param cfg: Config object to initialize (cast to AzureConfig).
        :param dct: Dictionary containing 'region'.
        """
        config = cast(AzureConfig, cfg)
        config._region = dct["region"]

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Config:
        """
        Deserialize AzureConfig from configuration or cache.

        Deserializes credentials and resources, then initializes the AzureConfig
        object, prioritizing cached configuration.

        :param config: Configuration dictionary.
        :param cache: Cache object.
        :param handlers: Logging handlers.
        :return: AzureConfig instance.
        """
        cached_config = cache.get_config("azure")
        # FIXME: use future annotations (see sebs/faas/system)
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

    def update_cache(self, cache: Cache):
        """
        Update the user cache with Azure configuration.

        Saves region, credentials, and resources to the cache.
        The changes are directly written to the file system.

        :param cache: Cache object.
        """
        cache.update_config(val=self.region, keys=["azure", "region"])
        self.credentials.update_cache(cache)
        self.resources.update_cache(cache)

    def serialize(self) -> dict:
        """
        Serialize AzureConfig to a dictionary.

        Includes region, credentials, and resources.

        :return: Dictionary representation of AzureConfig.
        """
        out = {
            "name": "azure",
            "region": self._region,
            "credentials": self._credentials.serialize(),
            "resources": self._resources.serialize(),
        }
        return out
