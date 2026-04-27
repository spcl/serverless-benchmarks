import docker
from typing import cast, Tuple

from sebs.gcp.config import GCPConfig, GCPCredentials
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
        self.config: GCPConfig = config
        self.creds = service_account.Credentials.from_service_account_file(
            self.config.credentials.gcp_credentials,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        self.ar_client = build("artifactregistry", "v1", credentials=self.creds)

    def registry_name(
        self, benchmark: str, language_name: str, language_version: str, architecture: str
    ) -> Tuple[str, str, str, str]:

        project_id = self.config.credentials.project_name
        region = self.config.region
        registry_name = f"{region}-docker.pkg.dev/{project_id}"
        repository_name = self.config.resources.get_container_repository(
            self.config, self.ar_client
        )

        image_tag = self.system_config.benchmark_image_tag(
            self.name(), benchmark, language_name, language_version, architecture
        )
        image_uri = f"{registry_name}/{repository_name}/{benchmark}:{image_tag}"

        return registry_name, repository_name, image_tag, image_uri

    def find_image(self, repository_name, image_tag) -> bool:
        try:
            credentials = cast(GCPCredentials, self.config.credentials)
            parent = (
                f"projects/{credentials.project_name}"
                f"/locations/{self.config.region}"
                f"/repositories/{repository_name}"
            )
            response = (
                self.ar_client.projects()
                .locations()
                .repositories()
                .dockerImages()
                .list(parent=parent)
                .execute()
            )
            if "dockerImages" in response:
                for image in response["dockerImages"]:
                    if image_tag in image.get("tags", []):
                        return True
        except HttpError as e:
            if e.resp.status == 404:
                return False
            raise e
        return False

    def push_to_registry(
        self,
        benchmark: str,
        language_name: str,
        language_version: str,
        architecture: str,
    ) -> str:
        image_uri = super().push_to_registry(
            benchmark, language_name, language_version, architecture
        )
        return self.resolve_image_uri(image_uri)

    def build_base_image(
        self,
        directory: str,
        language,
        language_version: str,
        architecture: str,
        benchmark: str,
        is_cached: bool,
        builder_image: str,
    ) -> Tuple[bool, str, float]:
        rebuilt, image_uri, size_mb = super().build_base_image(
            directory,
            language,
            language_version,
            architecture,
            benchmark,
            is_cached,
            builder_image,
        )
        return rebuilt, self.resolve_image_uri(image_uri), size_mb

    def resolve_image_uri(self, image_uri: str) -> str:
        """Resolve a tag URI to an immutable digest URI when Docker exposes one."""
        if "@sha256:" in image_uri:
            return image_uri

        repository = image_uri.rsplit(":", 1)[0]
        try:
            image = self.docker_client.images.get(image_uri)
        except docker.errors.ImageNotFound:
            self.logging.warning(
                f"Could not inspect pushed image {image_uri}; deploying mutable tag reference."
            )
            return image_uri

        repo_digests = image.attrs.get("RepoDigests", [])
        for digest_uri in repo_digests:
            if digest_uri.split("@", 1)[0] == repository:
                self.logging.info(f"Resolved image {image_uri} to digest {digest_uri}")
                return digest_uri

        self.logging.warning(
            f"No registry digest found for {image_uri}; deploying mutable tag reference."
        )
        return image_uri

    def push_image(self, repository_uri, image_tag):
        self.logging.info("Authenticating Docker against Artifact Registry...")
        self.creds.refresh(Request())
        auth_token = self.creds.token

        try:
            self.docker_client.login(
                username="oauth2accesstoken", password=auth_token, registry=repository_uri
            )
            super().push_image(repository_uri, image_tag)
            self.logging.info(f"Successfully pushed the image to registry {repository_uri}.")
        except docker.errors.DockerException as e:
            self.logging.error(f"Failed to push the image to registry {repository_uri}.")
            self.logging.error(f"Error: {str(e)}")
            raise RuntimeError("Couldn't push to registry.")
