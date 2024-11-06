import docker
import os
import platform
import shutil
from typing import Tuple

import boto3
from botocore.exceptions import ClientError
from mypy_boto3_ecr import ECRClient

from sebs.aws.config import AWSConfig
from sebs.config import SeBSConfig
from sebs.faas.container import DockerContainer
from sebs.utils import DOCKER_DIR


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
        docker_client: docker.client,
    ):

        super().__init__(system_config, docker_client)
        self.ecr_client = session.client(service_name="ecr", region_name=config.region)
        self.config = config

    @property
    def client(self) -> ECRClient:
        return self.ecr_client

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

    def push_image_to_repository(self, repository_uri, image_tag):

        username, password, registry_url = self.config.resources.ecr_repository_authorization(
            self.client
        )

        try:
            self.docker_client.login(username=username, password=password, registry=registry_url)
            self.push_image(repository_uri, image_tag)
            self.logging.info(f"Successfully pushed the image to registry {repository_uri}.")
        except docker.errors.APIError as e:
            self.logging.error(f"Failed to push the image to registry {repository_uri}.")
            self.logging.error(f"Error: {str(e)}")
            raise RuntimeError("Couldn't push to Docker registry")

    def build_base_image(
        self,
        directory: str,
        language_name: str,
        language_version: str,
        architecture: str,
        benchmark: str,
        is_cached: bool,
    ) -> Tuple[bool, str]:
        """
        When building function for the first time (according to SeBS cache),
        check if Docker image is available in the registry.
        If yes, then skip building.
        If no, then continue building.

        For every subsequent build, we rebuild image and push it to the
        registry. These are triggered by users modifying code and enforcing
        a build.
        """

        account_id = self.config.credentials.account_id
        region = self.config.region
        registry_name = f"{account_id}.dkr.ecr.{region}.amazonaws.com"

        repository_name = self.config.resources.get_ecr_repository(self.client)

        image_tag = self.system_config.benchmark_image_tag(
            self.name(), benchmark, language_name, language_version, architecture
        )
        repository_uri = f"{registry_name}/{repository_name}:{image_tag}"

        # cached package, rebuild not enforced -> check for new one
        # if cached is true, no need to build and push the image.
        if is_cached:
            if self.find_image(repository_name, image_tag):
                self.logging.info(
                    f"Skipping building AWS Docker package for {benchmark}, using "
                    f"Docker image {repository_name}:{image_tag} from registry: "
                    f"{registry_name}."
                )
                return False, repository_uri
            else:
                # image doesn't exist, let's continue
                self.logging.info(
                    f"Image {repository_name}:{image_tag} doesn't exist in the registry, "
                    f"building the image for {benchmark}."
                )

        build_dir = os.path.join(directory, "docker")
        os.makedirs(build_dir, exist_ok=True)

        shutil.copy(
            os.path.join(DOCKER_DIR, self.name(), language_name, "Dockerfile.function"),
            os.path.join(build_dir, "Dockerfile"),
        )
        for fn in os.listdir(directory):
            if fn not in ("index.js", "__main__.py"):
                file = os.path.join(directory, fn)
                shutil.move(file, build_dir)

        with open(os.path.join(build_dir, ".dockerignore"), "w") as f:
            f.write("Dockerfile")

        builder_image = self.system_config.benchmark_base_images(
            self.name(), language_name, architecture
        )[language_version]
        self.logging.info(f"Build the benchmark base image {repository_name}:{image_tag}.")

        isa = platform.processor()
        if (isa == "x86_64" and architecture != "x64") or (
            isa == "arm64" and architecture != "arm64"
        ):
            self.logging.warning(
                f"Building image for architecture: {architecture} on CPU architecture: {isa}. "
                "This step requires configured emulation. If the build fails, please consult "
                "our documentation. We recommend QEMU as it can be configured to run automatically."
            )

        buildargs = {"VERSION": language_version, "BASE_IMAGE": builder_image}
        image, _ = self.docker_client.images.build(
            tag=repository_uri, path=build_dir, buildargs=buildargs
        )

        self.logging.info(
            f"Push the benchmark base image {repository_name}:{image_tag} "
            f"to registry: {registry_name}."
        )

        self.push_image_to_repository(repository_uri, image_tag)

        return True, repository_uri
