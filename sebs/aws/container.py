"""AWS ECR container management for SeBS.

This module provides the ECRContainer class which handles Docker container
operations for AWS Lambda deployments using Amazon Elastic Container Registry (ECR).
It extends the base DockerContainer class with AWS-specific functionality for
image registry operations.

Key classes:
    ECRContainer: AWS ECR-specific container management
"""

import docker
from typing import Tuple

import boto3
from botocore.exceptions import ClientError
from mypy_boto3_ecr import ECRClient

from sebs.aws.config import AWSConfig
from sebs.config import SeBSConfig
from sebs.faas.container import DockerContainer


class ECRContainer(DockerContainer):
    """AWS ECR container management for SeBS.

    This class handles Docker container operations specifically for AWS Lambda
    deployments using Amazon Elastic Container Registry (ECR). It provides
    functionality for building, tagging, and pushing container images to ECR.

    Attributes:
        ecr_client: AWS ECR client for registry operations
        config: AWS-specific configuration
    """

    @staticmethod
    def name() -> str:
        """Get the name of this container system.

        Returns:
            str: System name ('aws')
        """
        return "aws"

    @staticmethod
    def typename() -> str:
        """Get the type name of this container system.

        Returns:
            str: Type name ('AWS.ECRContainer')
        """
        return "AWS.ECRContainer"

    def __init__(
        self,
        system_config: SeBSConfig,
        session: boto3.session.Session,
        config: AWSConfig,
        docker_client: docker.client.DockerClient,
    ) -> None:
        """Initialize ECR container manager.

        Args:
            system_config: SeBS system configuration
            session: AWS boto3 session
            config: AWS-specific configuration
            docker_client: Docker client for local operations
        """
        super().__init__(system_config, docker_client)
        self.ecr_client = session.client(service_name="ecr", region_name=config.region)
        self.config = config

    @property
    def client(self) -> ECRClient:
        """Get the ECR client.

        Returns:
            ECRClient: AWS ECR client for registry operations
        """
        return self.ecr_client

    def registry_name(
        self, benchmark: str, language_name: str, language_version: str, architecture: str
    ) -> Tuple[str, str, str, str]:
        """Generate ECR registry details for a benchmark image.

        Creates the registry name, repository name, image tag, and full image URI
        for a specific benchmark configuration.

        Args:
            benchmark: Name of the benchmark
            language_name: Programming language (e.g., 'python', 'nodejs')
            language_version: Language version (e.g., '3.8', '14')
            architecture: Target architecture (e.g., 'x64', 'arm64')

        Returns:
            Tuple[str, str, str, str]: Registry name, repository name, image tag, and image URI
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
        """Check if an image exists in the ECR repository.

        Args:
            repository_name: Name of the ECR repository
            image_tag: Tag of the image to search for

        Returns:
            bool: True if the image exists, False otherwise
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

    def push_image(self, repository_uri: str, image_tag: str) -> None:
        """Push a Docker image to ECR.

        Authenticates with ECR using temporary credentials and pushes the
        specified image to the repository.

        Args:
            repository_uri: URI of the ECR repository
            image_tag: Tag of the image to push

        Raises:
            RuntimeError: If the push operation fails
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
