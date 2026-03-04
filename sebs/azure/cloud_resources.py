"""Azure cloud resource management for SeBS.

This module manages deployed special resources in Azure cloud, particularly
CosmosDB accounts that require special handling for authentication and
configuration management.
"""

import json
from typing import Dict, Optional

from sebs.azure.cli import AzureCLI


class CosmosDBAccount:
    """Azure CosmosDB account configuration and management.

    Manages CosmosDB account information including account name, endpoint URL,
    and authentication credentials. Provides methods for querying account
    details from Azure and serialization for caching.

    Attributes:
        _account_name (str): Name of the CosmosDB account
        _url (str): Document endpoint URL for the account
        _credential (str): Primary master key for authentication
    """

    @property
    def account_name(self) -> str:
        """Get the CosmosDB account name.

        Returns:
            str: The name of the CosmosDB account.
        """
        return self._account_name

    @property
    def url(self) -> str:
        """Get the CosmosDB document endpoint URL.

        Returns:
            str: The document endpoint URL for the CosmosDB account.
        """
        return self._url

    @property
    def credential(self) -> str:
        """Get the CosmosDB authentication credential.

        Returns:
            str: The primary master key for CosmosDB authentication.
        """
        return self._credential

    def __init__(self, account_name: str, url: str, credential: str) -> None:
        """Initialize CosmosDB account configuration.

        Args:
            account_name (str): Name of the CosmosDB account
            url (str): Document endpoint URL for the account
            credential (str): Primary master key for authentication
        """
        super().__init__()
        self._account_name = account_name
        self._url = url
        self._credential = credential

    @staticmethod
    def from_cache(account_name: str, url: str, credential: str) -> "CosmosDBAccount":
        """Create CosmosDB account instance from cached data.

        Args:
            account_name (str): Name of the CosmosDB account
            url (str): Document endpoint URL for the account
            credential (str): Primary master key for authentication

        Returns:
            CosmosDBAccount: New instance with provided configuration.
        """
        return CosmosDBAccount(account_name, url, credential)

    @staticmethod
    def from_allocation(
        account_name: str, resource_group: str, cli_instance: AzureCLI, url: Optional[str] = None
    ) -> "CosmosDBAccount":
        """Create CosmosDB account instance by querying Azure.

        Queries Azure CLI to retrieve account configuration including
        endpoint URL and authentication credentials.

        Args:
            account_name (str): Name of the CosmosDB account
            resource_group (str): Azure resource group containing the account
            cli_instance (AzureCLI): Azure CLI instance for executing commands
            url (Optional[str]): Pre-known URL, if None will query from Azure

        Returns:
            CosmosDBAccount: New instance with queried configuration.
        """
        if url is None:
            url = CosmosDBAccount.query_url(
                account_name,
                resource_group,
                cli_instance,
            )

        credential = CosmosDBAccount.query_credentials(
            account_name,
            resource_group,
            cli_instance,
        )

        return CosmosDBAccount(account_name, url, credential)

    @staticmethod
    def query_url(account_name: str, resource_group: str, cli_instance: AzureCLI) -> str:
        """Query CosmosDB account endpoint URL from Azure.

        Uses Azure CLI to retrieve the document endpoint URL for the
        specified CosmosDB account.

        Args:
            account_name (str): Name of the CosmosDB account
            resource_group (str): Azure resource group containing the account
            cli_instance (AzureCLI): Azure CLI instance for executing commands

        Returns:
            str: The document endpoint URL for the CosmosDB account.

        Raises:
            RuntimeError: If Azure CLI command fails.
            KeyError: If the expected response structure is not found.
        """
        # Find the endpoint URL
        ret = cli_instance.execute(
            f" az cosmosdb show --name {account_name} " f" --resource-group {resource_group} "
        )
        ret_dct = json.loads(ret.decode("utf-8"))
        return ret_dct["documentEndpoint"]

    @staticmethod
    def query_credentials(account_name: str, resource_group: str, cli_instance: AzureCLI) -> str:
        """Query CosmosDB account authentication credentials from Azure.

        Uses Azure CLI to retrieve the primary master key for the
        specified CosmosDB account.

        Args:
            account_name (str): Name of the CosmosDB account
            resource_group (str): Azure resource group containing the account
            cli_instance (AzureCLI): Azure CLI instance for executing commands

        Returns:
            str: The primary master key for CosmosDB authentication.

        Raises:
            RuntimeError: If Azure CLI command fails.
            KeyError: If the expected response structure is not found.
        """
        # Read the master key to access CosmosDB account
        ret = cli_instance.execute(
            f" az cosmosdb keys list --name {account_name} " f" --resource-group {resource_group} "
        )
        ret_dct = json.loads(ret.decode("utf-8"))
        credential = ret_dct["primaryMasterKey"]

        return credential

    def serialize(self) -> Dict[str, str]:
        """Serialize CosmosDB account configuration to dictionary.

        Returns:
            Dict[str, str]: Dictionary containing account configuration with keys:
                - account_name: The CosmosDB account name
                - url: The document endpoint URL
                - credential: The primary master key
        """
        return {
            "account_name": self._account_name,
            "url": self._url,
            "credential": self._credential,
        }

    @staticmethod
    def deserialize(obj: Dict[str, str]) -> "CosmosDBAccount":
        """Deserialize CosmosDB account configuration from dictionary.

        Args:
            obj (Dict[str, str]): Dictionary containing account configuration
                with required keys: account_name, url, credential

        Returns:
            CosmosDBAccount: New instance with deserialized configuration.

        Raises:
            KeyError: If required keys are missing from the dictionary.
        """
        return CosmosDBAccount.from_cache(obj["account_name"], obj["url"], obj["credential"])
