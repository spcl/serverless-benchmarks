import docker
from typing import Tuple

import boto3
from botocore.exceptions import ClientError
from mypy_boto3_ecr import ECRClient

from sebs.aws.config import AWSConfig
from sebs.config import SeBSConfig
from sebs.faas.container import DockerContainer


class ECRContainer(DockerContainer):
    """Manages Docker container images in AWS Elastic Container Registry (ECR)."""
    @staticmethod
    def name():
        """Return the name of the container platform (aws)."""
        return "aws"

    @staticmethod
    def typename() -> str:
        """Return the type name of the ECRContainer class."""
        return "AWS.ECRContainer"

    def __init__(
        self,
        system_config: SeBSConfig,
        session: boto3.session.Session,
        config: AWSConfig,
        docker_client: docker.client.DockerClient,
    ):
        """
        Initialize ECRContainer.

        :param system_config: SeBS system configuration.
        :param session: Boto3 session.
        :param config: AWS-specific configuration.
        :param docker_client: Docker client instance.
        """
        super().__init__(system_config, docker_client)
        self.ecr_client = session.client(service_name="ecr", region_name=config.region)
        self.config = config

    @property
    def client(self) -> ECRClient:
        """Return the Boto3 ECR client."""
        return self.ecr_client

    def registry_name(
        self, benchmark: str, language_name: str, language_version: str, architecture: str
    ) -> Tuple[str, str, str, str]:
        """
        Generate ECR registry and image names.

        :param benchmark: Name of the benchmark.
        :param language_name: Name of the programming language.
        :param language_version: Version of the programming language.
        :param architecture: CPU architecture of the image.
        :return: Tuple containing:
            - registry_name (e.g., {account_id}.dkr.ecr.{region}.amazonaws.com)
            - repository_name (e.g., sebs-benchmarks-{resources_id})
            - image_tag (e.g., aws-benchmark-python-3.8-x64)
            - image_uri (e.g., {registry_name}/{repository_name}:{image_tag})
        """
        account_id = self.config.credentials.account_id
        region = self.config.region
        registry_name = f"{account_id}.dkr.ecr.{region}.amazonaws.com"

        repository_name = self.config.resources.get_ecr_repository(self.client)
        image_tag = self.system_config.benchmark_image_tag(
            self.name(), benchmark, language_name, language_version, architecture
        )
        image_uri = f"{registry_name}/{repository_name}:{image_tag}"

        return registry_name, repository_name, image_tag, image_uri

    def find_image(self, repository_name: str, image_tag: str) -> bool:
        """
        Check if an image with a specific tag exists in the ECR repository.

        :param repository_name: Name of the ECR repository.
        :param image_tag: Tag of the image.
        :return: True if the image exists, False otherwise.
        """
        try:
            response = self.ecr_client.describe_images(
                repositoryName=repository_name, imageIds=[{"imageTag": image_tag}]
            )
            if response["imageDetails"]:
                return True
        except ClientError:
            return False

        return False

    def push_image(self, repository_uri: str, image_tag: str):
        """
        Push a Docker image to the ECR repository.

        Authenticates with ECR using credentials from AWSResources.

        :param repository_uri: URI of the ECR repository.
        :param image_tag: Tag of the image to push.
        :raises RuntimeError: If pushing the image fails.
        """
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
