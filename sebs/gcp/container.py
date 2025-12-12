import docker
from typing import Tuple

from sebs.gcp.config import GCPConfig
from sebs.config import SeBSConfig
from sebs.faas.container import DockerContainer
from googleapiclient.discovery import build
from google.oauth2 import service_account
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request


class GCRContainer(DockerContainer):
    @staticmethod
    def name():
        return "gcp"

    @staticmethod
    def typename() -> str:
        return "GCP.GCRContainer"

    def __init__(
        self,
        system_config: SeBSConfig,
        config: GCPConfig,
        docker_client: docker.client.DockerClient,
    ):
        super().__init__(system_config, docker_client)
        self.config = config
        self.creds = service_account.Credentials.from_service_account_file(self.config.credentials.gcp_credentials, scopes=["https://www.googleapis.com/auth/cloud-platform"])
        self.ar_client = build("artifactregistry", "v1", credentials=self.creds)

    def registry_name(
        self, benchmark: str, language_name: str, language_version: str, architecture: str
    ) -> Tuple[str, str, str, str]:
        
        project_id = self.config.credentials.project_name
        region = self.config.region
        registry_name = f"{region}-docker.pkg.dev/{project_id}"
        repository_name = self.config.resources.get_container_repository(self.config, self.ar_client)
        
        image_tag = self.system_config.benchmark_image_tag(
            self.name(), benchmark, language_name, language_version, architecture
        )
        image_uri = f"{registry_name}/{repository_name}/{benchmark}:{image_tag}"

        return registry_name, repository_name, image_tag, image_uri

    def find_image(self, repository_name, image_tag) -> bool:
        try:
            response = self.ar_client.projects().locations().repositories().dockerImages().list(
                parent=f"projects/{self.config.credentials.project_id}/locations/{self.config.region}/repositories/{repository_name}"
            )
            if "dockerImages" in response:
                for image in response["dockerImages"]:
                    if "latest" in image["tags"] and image_tag in image["tags"]:
                        return True
        except HttpError as e:
            if (e.content.code == 404):
                return False
            raise e
        return False

    def get_adapted_image_name(self, image_name: str, language_name: str,language_version: str, architecture: str):
        if language_name == "python":
            return f"python:{language_version}-slim"
        elif language_name == "nodejs":
            return f"node:{language_version}-slim"

        return image_name

    def push_image(self, repository_uri, image_tag):        
        self.logging.info("Authenticating Docker against Artifact Registry...")
        self.creds.refresh(Request())
        auth_token = self.creds.token

        try:
            self.docker_client.login(
                username="oauth2accesstoken",
                password=auth_token,
                registry=repository_uri
            )
            super().push_image(repository_uri, image_tag)
            self.logging.info(f"Successfully pushed the image to registry {repository_uri}.")
        except docker.errors.DockerException as e:
            self.logging.error(f"Failed to push the image to registry {repository_uri}.")
            self.logging.error(f"Error: {str(e)}")
            raise RuntimeError("Couldn't push to registry.")
