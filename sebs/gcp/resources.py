"""System resource management for Google Cloud Platform.

This module provides the GCPSystemResources class that manages all GCP resources
required for serverless benchmarking, including storage, NoSQL databases, and
CLI tools. It coordinates resource allocation and provides unified access to
GCP services.

Classes:
    GCPSystemResources: Main resource manager for GCP services

Example:
    Creating and using GCP system resources:
    
        resources = GCPSystemResources(system_config, gcp_config, cache, docker_client, handlers)
        storage = resources.get_storage(replace_existing=False)
        datastore = resources.get_nosql_storage()
"""

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
    """System resource manager for Google Cloud Platform services.
    
    Manages and provides access to all GCP services required for serverless
    benchmarking including Cloud Storage, Firestore/Datastore, and gcloud CLI.
    Handles resource initialization, configuration, and cleanup.
    
    Attributes:
        _storage: Cloud Storage instance for object storage
        _nosql_storage: Datastore instance for NoSQL operations
        _cli_instance: gcloud CLI interface for administrative operations
        _system_config: SeBS system configuration
        _logging_handlers: Logging configuration
    """
    @staticmethod
    def typename() -> str:
        """Get the type name for this resource manager.
        
        Returns:
            Type name string for GCP system resources
        """
        return "GCP.SystemResources"

    @property
    def config(self) -> GCPConfig:
        """Get the GCP configuration instance.
        
        Returns:
            GCP configuration with credentials and settings
        """
        return cast(GCPConfig, self._config)

    def __init__(
        self,
        system_config: SeBSConfig,
        config: GCPConfig,
        cache_client: Cache,
        docker_client: docker.client,
        logger_handlers: LoggingHandlers,
    ) -> None:
        """Initialize GCP system resources manager.
        
        Args:
            system_config: SeBS system configuration
            config: GCP-specific configuration
            cache_client: Cache instance for resource state
            docker_client: Docker client for containerized operations
            logger_handlers: Logging configuration
        """
        super().__init__(config, cache_client, docker_client)

        self._logging_handlers = logger_handlers
        self._storage: Optional[GCPStorage] = None
        self._nosql_storage: Optional[Datastore] = None
        self._cli_instance: Optional[GCloudCLI] = None
        self._system_config = system_config

    def get_storage(self, replace_existing: Optional[bool] = None) -> GCPStorage:
        """Get or create the Cloud Storage instance.
        
        Provides access to Google Cloud Storage for persistent object storage.
        Creates the storage instance if it doesn't exist, or updates the
        replace_existing setting if provided.
        
        Args:
            replace_existing: Whether to replace existing benchmark input data
            
        Returns:
            Initialized GCP storage instance
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
        """Get or create the Datastore instance for NoSQL operations.
        
        Provides access to Google Cloud Firestore/Datastore for NoSQL
        database operations required by benchmarks.
        
        Returns:
            Initialized Datastore instance
        """
        if not self._nosql_storage:
            self._nosql_storage = Datastore(
                self.cli_instance, self._cache_client, self.config.resources, self.config.region
            )
        return self._nosql_storage

    @property
    def cli_instance(self) -> GCloudCLI:
        """Get or create the gcloud CLI instance.
        
        Provides access to a containerized gcloud CLI for administrative
        operations. Initializes and authenticates the CLI if needed.
        
        Returns:
            Authenticated gcloud CLI instance
        """
        if self._cli_instance is None:
            self._cli_instance = GCloudCLI(
                self.config.credentials, self._system_config, self._docker_client
            )
            self._cli_instance_stop = True

            self._cli_instance.login(self.config.credentials.project_name)
        return self._cli_instance

    def initialize_cli(self, cli: GCloudCLI) -> None:
        """Initialize with an existing CLI instance.
        
        Uses a pre-configured CLI instance instead of creating a new one.
        
        Args:
            cli: Pre-configured gcloud CLI instance
        """
        self._cli_instance = cli
        self._cli_instance_stop = False

    def shutdown(self) -> None:
        """Shutdown system resources and clean up.
        
        Stops the gcloud CLI container if it was created by this instance.
        """
        if self._cli_instance and self._cli_instance_stop:
            self._cli_instance.shutdown()
