import docker
from typing import Tuple

import boto3
from botocore.exceptions import ClientError
from mypy_boto3_ecr import ECRClient

from sebs.aws.config import AWSConfig
from sebs.config import SeBSConfig
from sebs.faas.container import DockerContainer


class ECRContainer(DockerContainer):
    @staticmethod
    def name():
        return "aws"

    @staticmethod
    def typename() -> str:
        return "AWS.ECRContainer"

    def __init__(
        self,
        system_config: SeBSConfig,
        session: boto3.session.Session,
        config: AWSConfig,
        docker_client: docker.client.DockerClient,
    ):

        super().__init__(system_config, docker_client)
        self.ecr_client = session.client(service_name="ecr", region_name=config.region)
        self.config = config

    @property
    def client(self) -> ECRClient:
        return self.ecr_client

    def registry_name(
        self, benchmark: str, language_name: str, language_version: str, architecture: str
    ) -> Tuple[str, str, str, str]:

        account_id = self.config.credentials.account_id
        region = self.config.region
        registry_name = f"{account_id}.dkr.ecr.{region}.amazonaws.com"

        repository_name = self.config.resources.get_ecr_repository(self.client)
        image_tag = self.system_config.benchmark_image_tag(
            self.name(), benchmark, language_name, language_version, architecture
        )
        image_uri = f"{registry_name}/{repository_name}:{image_tag}"

        return registry_name, repository_name, image_tag, image_uri

    def find_image(self, repository_name, image_tag) -> bool:
        try:
            response = self.ecr_client.describe_images(
                repositoryName=repository_name, imageIds=[{"imageTag": image_tag}]
            )
            if response["imageDetails"]:
                return True
        except ClientError:
            return False

        return False

    def push_image(self, repository_uri, image_tag):

        username, password, registry_url = self.config.resources.ecr_repository_authorization(
            self.client
        )

        try:
            self.docker_client.login(username=username, password=password, registry=registry_url)
            super().push_image(repository_uri, image_tag)
            self.logging.info(f"Successfully pushed the image to registry {repository_uri}.")
        except docker.errors.APIError as e:
            self.logging.error(f"Failed to push the image to registry {repository_uri}.")
            self.logging.error(f"Error: {str(e)}")
            raise RuntimeError("Couldn't push to Docker registry")
