"""Docker container management for OpenWhisk functions in SeBS.

This module provides OpenWhisk-specific Docker container management functionality,
handling Docker image registry configuration, image tagging, and repository naming
for OpenWhisk function deployments.

Classes:
    OpenWhiskContainer: OpenWhisk-specific Docker container management
"""

import docker
from typing import Tuple

from sebs.faas.container import DockerContainer
from sebs.config import SeBSConfig
from sebs.openwhisk.config import OpenWhiskConfig


class OpenWhiskContainer(DockerContainer):
    """
    OpenWhisk-specific Docker container management.
    
    This class extends the base DockerContainer to provide OpenWhisk-specific
    functionality for managing Docker images, registries, and container deployment.
    It handles Docker registry authentication and image URI generation for
    OpenWhisk function deployments.
    
    Attributes:
        config: OpenWhisk configuration containing registry settings
    
    Example:
        >>> container = OpenWhiskContainer(sys_config, ow_config, docker_client, True)
        >>> registry, repo, tag, uri = container.registry_name("benchmark", "python", "3.8", "x86_64")
    """
    
    @staticmethod
    def name() -> str:
        """
        Get the platform name identifier.
        
        Returns:
            Platform name as string
        """
        return "openwhisk"

    @staticmethod
    def typename() -> str:
        """
        Get the container type name.
        
        Returns:
            Container type name as string
        """
        return "OpenWhisk.Container"

    def __init__(
        self,
        system_config: SeBSConfig,
        config: OpenWhiskConfig,
        docker_client: docker.client,
        experimental_manifest: bool,
    ) -> None:
        """
        Initialize OpenWhisk container manager.
        
        Args:
            system_config: Global SeBS system configuration
            config: OpenWhisk-specific configuration settings
            docker_client: Docker client for container operations
            experimental_manifest: Whether to use experimental manifest features
        """
        super().__init__(system_config, docker_client, experimental_manifest)
        self.config = config

    def registry_name(
        self, benchmark: str, language_name: str, language_version: str, architecture: str
    ) -> Tuple[str, str, str, str]:
        """
        Generate Docker registry information for a benchmark image.
        
        This method creates the appropriate registry name, repository name, image tag,
        and complete image URI based on the benchmark parameters and OpenWhisk
        configuration. It handles both custom registries and Docker Hub.
        
        Args:
            benchmark: Name of the benchmark
            language_name: Programming language (e.g., 'python', 'nodejs')
            language_version: Language version (e.g., '3.8', '14')
            architecture: Target architecture (e.g., 'x86_64')
        
        Returns:
            Tuple containing:
                - Registry name (e.g., "my-registry.com" or "Docker Hub")
                - Full repository name with registry prefix
                - Image tag
                - Complete image URI
        
        Example:
            >>> registry, repo, tag, uri = container.registry_name("test", "python", "3.8", "x86_64")
            >>> # Returns: ("Docker Hub", "sebs", "openwhisk-test-python-3.8-x86_64", "sebs:openwhisk-test-python-3.8-x86_64")
        """
        registry_name = self.config.resources.docker_registry

        # We need to retag created images when pushing to registry other
        # than default
        repository_name = self.system_config.docker_repository()
        image_tag = self.system_config.benchmark_image_tag(
            self.name(), benchmark, language_name, language_version, architecture
        )
        if registry_name is not None and registry_name != "":
            repository_name = f"{registry_name}/{repository_name}"
        else:
            registry_name = "Docker Hub"
        image_uri = f"{repository_name}:{image_tag}"

        return registry_name, repository_name, image_tag, image_uri
