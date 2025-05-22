from typing import cast, Optional

from sebs.config import SeBSConfig
from sebs.gcp.config import GCPConfig
from sebs.gcp.storage import GCPStorage
from sebs.gcp.datastore import Datastore
from sebs.gcp.cli import GCloudCLI
from sebs.cache import Cache
from sebs.faas.resources import SystemResources
from sebs.utils import LoggingHandlers

import docker


class GCPSystemResources(SystemResources):
    """
    Manages system-level resources for Google Cloud Platform (GCP),
    such as Cloud Storage, Datastore, and the GCloud CLI wrapper.
    """
    @staticmethod
    def typename() -> str:
        """Return the type name of the system resources class."""
        return "GCP.SystemResources"

    @property
    def config(self) -> GCPConfig:
        """Return the GCP-specific configuration."""
        return cast(GCPConfig, self._config)

    def __init__(
        self,
        system_config: SeBSConfig,
        config: GCPConfig,
        cache_client: Cache,
        docker_client: docker.client,
        logger_handlers: LoggingHandlers,
    ):
        """
        Initialize GCPSystemResources.

        :param system_config: SeBS system configuration.
        :param config: GCP-specific configuration.
        :param cache_client: Cache client instance.
        :param docker_client: Docker client instance.
        :param logger_handlers: Logging handlers.
        """
        super().__init__(config, cache_client, docker_client)

        self._logging_handlers = logger_handlers
        self._storage: Optional[GCPStorage] = None
        self._nosql_storage: Optional[Datastore] = None
        self._cli_instance: Optional[GCloudCLI] = None
        self._cli_instance_stop: bool = False # Flag to indicate if this instance owns the CLI
        self._system_config = system_config

    def get_storage(self, replace_existing: Optional[bool] = None) -> GCPStorage:
        """
        Get or initialize the GCP Cloud Storage client.

        Creates a GCPStorage client instance if it doesn't exist.

        :param replace_existing: If True, replace existing files in input buckets.
                                 Defaults to False if None.
        :return: GCPStorage instance.
        """
        if not self._storage:
            self._storage = GCPStorage(
                self.config.region,
                self._cache_client,
                self.config.resources,
                replace_existing if replace_existing is not None else False,
            )
            self._storage.logging_handlers = self._logging_handlers
        elif replace_existing is not None:
            self._storage.replace_existing = replace_existing
        return self._storage

    def get_nosql_storage(self) -> Datastore:
        """
        Get or initialize the GCP Datastore client.

        Creates a Datastore client instance if it doesn't exist.
        Requires GCloud CLI for initial setup if resources are not cached.

        :return: Datastore instance.
        """
        if not self._nosql_storage:
            self._nosql_storage = Datastore(
                self.cli_instance, self._cache_client, self.config.resources, self.config.region
            )
        return self._nosql_storage

    @property
    def cli_instance(self) -> GCloudCLI:
        """
        Get or initialize the GCloud CLI wrapper instance.

        If the CLI instance doesn't exist, it's created, and a login is performed
        using the configured credentials and project name. This instance will be
        stopped on shutdown if it was created by this method.

        :return: GCloudCLI instance.
        """
        if self._cli_instance is None:
            self._cli_instance = GCloudCLI(
                self.config.credentials, self._system_config, self._docker_client
            )
            self._cli_instance_stop = True # This instance manages the CLI lifecycle

            self._cli_instance.login(self.config.credentials.project_name)
        return self._cli_instance

    def initialize_cli(self, cli: GCloudCLI):
        """
        Initialize with an externally managed GCloud CLI instance.

        This allows sharing a single GCloudCLI Docker container. The provided
        CLI instance will not be stopped on shutdown by this GCPSystemResources instance.

        :param cli: An existing GCloudCLI instance.
        """
        self._cli_instance = cli
        self._cli_instance_stop = False # This instance does not manage the CLI lifecycle

    def shutdown(self) -> None:
        """
        Shutdown the GCP system resources.

        Stops the GCloud CLI Docker container if it was started and is managed by
        this instance.
        """
        if self._cli_instance and self._cli_instance_stop:
            self._cli_instance.shutdown()
