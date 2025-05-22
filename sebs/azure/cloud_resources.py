import json
from typing import Optional

from sebs.azure.cli import AzureCLI

"""
Manages information about deployed special resources in Azure, specifically CosmosDB accounts.

This module provides a class to encapsulate CosmosDB account details and methods
for querying and serializing this information.
"""


class CosmosDBAccount:
    """
    Represents an Azure CosmosDB account with its name, URL, and credentials.
    """
    @property
    def account_name(self) -> str:
        """The name of the CosmosDB account."""
        return self._account_name

    @property
    def url(self) -> str:
        """The document endpoint URL of the CosmosDB account."""
        return self._url

    @property
    def credential(self) -> str:
        """The primary master key for accessing the CosmosDB account."""
        return self._credential

    def __init__(self, account_name: str, url: str, credential: str):
        """
        Initialize a CosmosDBAccount instance.

        :param account_name: The name of the CosmosDB account.
        :param url: The document endpoint URL.
        :param credential: The primary master key.
        """
        super().__init__()
        self._account_name = account_name
        self._url = url
        self._credential = credential

    @staticmethod
    def from_cache(account_name: str, url: str, credential: str) -> "CosmosDBAccount":
        """
        Create a CosmosDBAccount instance from cached values.

        :param account_name: The name of the CosmosDB account.
        :param url: The document endpoint URL.
        :param credential: The primary master key.
        :return: A CosmosDBAccount instance.
        """
        return CosmosDBAccount(account_name, url, credential)

    @staticmethod
    def from_allocation(
        account_name: str, resource_group: str, cli_instance: AzureCLI, url: Optional[str]
    ) -> "CosmosDBAccount":
        """
        Create a CosmosDBAccount instance by querying Azure for URL and credentials if not provided.

        :param account_name: The name of the CosmosDB account.
        :param resource_group: The resource group where the CosmosDB account resides.
        :param cli_instance: An instance of AzureCLI for executing commands.
        :param url: Optional pre-fetched URL. If None, it will be queried.
        :return: A CosmosDBAccount instance.
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
        """
        Query Azure for the document endpoint URL of a CosmosDB account.

        :param account_name: The name of the CosmosDB account.
        :param resource_group: The resource group of the CosmosDB account.
        :param cli_instance: An AzureCLI instance.
        :return: The document endpoint URL string.
        """
        # Find the endpoint URL
        ret = cli_instance.execute(
            f" az cosmosdb show --name {account_name} " f" --resource-group {resource_group} "
        )
        ret = json.loads(ret.decode("utf-8"))
        return ret["documentEndpoint"]

    @staticmethod
    def query_credentials(account_name: str, resource_group: str, cli_instance: AzureCLI) -> str:
        """
        Query Azure for the primary master key of a CosmosDB account.

        :param account_name: The name of the CosmosDB account.
        :param resource_group: The resource group of the CosmosDB account.
        :param cli_instance: An AzureCLI instance.
        :return: The primary master key string.
        """
        # Read the master key to access CosmosDB account
        ret = cli_instance.execute(
            f" az cosmosdb keys list --name {account_name} " f" --resource-group {resource_group} "
        )
        ret = json.loads(ret.decode("utf-8"))
        credential = ret["primaryMasterKey"]

        return credential

    def serialize(self) -> dict:
        """
        Serialize the CosmosDBAccount instance to a dictionary.

        :return: A dictionary containing account_name, url, and credential.
        """
        return {
            "account_name": self._account_name,
            "url": self._url,
            "credential": self._credential,
        }

    @staticmethod
    def deserialize(obj: dict) -> "CosmosDBAccount":
        """
        Deserialize a CosmosDBAccount instance from a dictionary.

        :param obj: A dictionary containing 'account_name', 'url', and 'credential'.
        :return: A CosmosDBAccount instance.
        """
        return CosmosDBAccount.from_cache(obj["account_name"], obj["url"], obj["credential"])
