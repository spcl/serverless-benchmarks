import docker
from typing import Tuple

from sebs.faas.container import DockerContainer
from sebs.config import SeBSConfig
from sebs.openwhisk.config import OpenWhiskConfig


class OpenWhiskContainer(DockerContainer):
    @staticmethod
    def name() -> str:
        return "openwhisk"

    @staticmethod
    def typename() -> str:
        return "OpenWhisk.Container"

    def __init__(
        self,
        system_config: SeBSConfig,
        config: OpenWhiskConfig,
        docker_client: docker.client,
        experimental_manifest: bool,
    ):
        super().__init__(system_config, docker_client, experimental_manifest)
        self.config = config

    def registry_name(
        self, benchmark: str, language_name: str, language_version: str, architecture: str
    ) -> Tuple[str, str, str, str]:

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
