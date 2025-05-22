import docker
from typing import Tuple

from sebs.faas.container import DockerContainer
from sebs.config import SeBSConfig
from sebs.openwhisk.config import OpenWhiskConfig


class OpenWhiskContainer(DockerContainer):
    """
    Manages Docker container images for OpenWhisk actions.

    Extends the base DockerContainer class to provide OpenWhisk-specific
    logic for determining registry and image names.
    """
    @staticmethod
    def name() -> str:
        """Return the name of the FaaS platform (openwhisk)."""
        return "openwhisk"

    @staticmethod
    def typename() -> str:
        """Return the type name of the OpenWhiskContainer class."""
        return "OpenWhisk.Container"

    def __init__(
        self,
        system_config: SeBSConfig,
        config: OpenWhiskConfig,
        docker_client: docker.client,
        experimental_manifest: bool,
    ):
        """
        Initialize OpenWhiskContainer.

        :param system_config: SeBS system configuration.
        :param config: OpenWhisk-specific configuration.
        :param docker_client: Docker client instance.
        :param experimental_manifest: Flag to use experimental Docker manifest features.
        """
        super().__init__(system_config, docker_client, experimental_manifest)
        self.config = config

    def registry_name(
        self, benchmark: str, language_name: str, language_version: str, architecture: str
    ) -> Tuple[str, str, str, str]:
        """
        Generate OpenWhisk-specific registry and image names.

        Constructs the image URI, potentially re-tagging it if a custom Docker
        registry is specified in the OpenWhisk configuration.

        :param benchmark: Name of the benchmark.
        :param language_name: Name of the programming language.
        :param language_version: Version of the programming language.
        :param architecture: CPU architecture of the image.
        :return: Tuple containing:
            - registry_display_name (e.g., "Docker Hub" or custom registry URL)
            - repository_name_for_image (e.g., {custom_registry}/{sebs_repository} or {sebs_repository})
            - image_tag (e.g., openwhisk-benchmark-python-3.8-x64)
            - image_uri (fully qualified image URI for push/pull)
        """
        registry_url = self.config.resources.docker_registry # Actual URL or None

        # `repository_name_on_registry` will be the full path on the registry if custom,
        # otherwise it's just the SeBS default repository name (for Docker Hub).
        sebs_repository = self.system_config.docker_repository()
        image_tag = self.system_config.benchmark_image_tag(
            self.name(), benchmark, language_name, language_version, architecture
        )

        if registry_url: # If a custom registry is specified
            repository_name_on_registry = f"{registry_url}/{sebs_repository}"
            registry_display_name = registry_url
        else: # Default to Docker Hub
            repository_name_on_registry = sebs_repository
            registry_display_name = "Docker Hub"
            
        image_uri = f"{repository_name_on_registry}:{image_tag}"

        return registry_display_name, repository_name_on_registry, image_tag, image_uri
