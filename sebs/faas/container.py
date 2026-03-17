# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
"""Docker container management for serverless function deployments.

This module provides the DockerContainer class for building and managing
Docker containers for serverless function deployments. It handles:

- Building benchmark Docker images for different platforms
- Cross-architecture container compilation with emulation
- Container registry operations (push/pull)
- Progress tracking for container operations
- Platform-specific container naming and tagging

The module supports container-based deployments across different serverless
platforms, with automatic detection of the host architecture and appropriate
configuration for cross-compilation when needed.
"""

from abc import abstractmethod
import docker
import platform
import os
import shutil
from typing import Tuple

from sebs.config import SeBSConfig
from sebs.docker_builder import DockerImageBuilder
from sebs.sebs_types import Language
from sebs.utils import LoggingBase, execute, get_resource_path


class DockerContainer(LoggingBase):
    """Abstract base class for Docker container management in serverless deployments.

    This class provides common functionality for building, pushing, and managing
    Docker containers for serverless function deployments. Each platform
    implementation (AWS, Azure, GCP, etc.) extends this class to provide
    platform-specific container handling.

    Key features:
    - Container image building with cross-architecture support
    - Container registry operations (push/pull/inspect)
    - Progress tracking for long-running operations
    - Platform-specific image naming and tagging
    - Caching and optimization for repeated builds

    Attributes:
        docker_client: Docker client for container operations
        experimental_manifest: Whether to use experimental manifest inspection
        system_config: SeBS configuration for image management
        _disable_rich_output: Flag to disable rich progress output
    """

    @staticmethod
    @abstractmethod
    def name() -> str:
        """Get the platform name for this container implementation.

        Returns:
            str: Platform name (e.g., 'aws', 'azure', 'gcp')
        """
        pass

    @property
    def disable_rich_output(self) -> bool:
        """Get whether rich output is disabled.

        Returns:
            bool: True if rich output is disabled, False otherwise
        """
        return self._disable_rich_output

    @disable_rich_output.setter
    def disable_rich_output(self, val: bool):
        """Set whether to disable rich output.

        Args:
            val: True to disable rich output, False to enable
        """
        self._disable_rich_output = val

    def __init__(
        self,
        system_config: SeBSConfig,
        docker_client: docker.client.DockerClient,
        experimental_manifest: bool = False,
    ):
        """Initialize the Docker container manager.

        Args:
            system_config: SeBS configuration for container management
            docker_client: Docker client for container operations
            experimental_manifest: Whether to use experimental manifest features
        """
        super().__init__()

        self.docker_client = docker_client
        self.experimental_manifest = experimental_manifest
        self.system_config = system_config
        self._disable_rich_output = False

    def find_image(self, repository_name: str, image_tag: str) -> bool:
        """Check if a Docker image exists in the registry.

        Attempts to find an image in the registry using either experimental
        manifest inspection (if enabled) or by attempting to pull the image.

        Args:
            repository_name: Name of the repository (e.g., 'my-repo/my-image')
            image_tag: Tag of the image to find

        Returns:
            bool: True if the image exists, False otherwise
        """
        if self.experimental_manifest:
            try:
                # This requires enabling experimental Docker features
                # Furthermore, it's not yet supported in the Python library
                execute(f"docker manifest inspect {repository_name}:{image_tag}")
                return True
            except RuntimeError:
                return False
        else:
            try:
                # default version requires pulling for an image
                self.docker_client.images.pull(repository=repository_name, tag=image_tag)
                return True
            except docker.errors.NotFound:
                return False

    def push_image(self, repository_uri: str, image_tag: str):
        """Push a Docker image to a container registry.

        Delegates to the static method in DockerImageBuilder for consistent
        image pushing with progress tracking across SeBS.

        Args:
            repository_uri: URI of the container registry repository
            image_tag: Tag of the image to push

        Raises:
            docker.errors.APIError: If the push operation fails
            RuntimeError: If an error occurs during the push stream
        """
        DockerImageBuilder.push_image_with_progress(
            self.docker_client,
            repository_uri,
            image_tag,
            self.logging,
            disable_rich_output=self.disable_rich_output,
        )

    @abstractmethod
    def registry_name(
        self,
        benchmark: str,
        language_name: str,
        language_version: str,
        architecture: str,
    ) -> Tuple[str, str, str, str]:
        """Generate registry name and image URI for a benchmark.

        Creates platform-specific naming for container images including
        registry URL, repository name, image tag, and complete image URI.

        Args:
            benchmark: Name of the benchmark (e.g., '110.dynamic-html')
            language_name: Programming language (e.g., 'python', 'nodejs')
            language_version: Language version (e.g., '3.8', '14')
            architecture: Target architecture (e.g., 'x64', 'arm64')

        Returns:
            Tuple[str, str, str, str]: Registry name, repository name, image tag, full image URI
        """
        pass

    def push_to_registry(
        self,
        benchmark: str,
        language_name: str,
        language_version: str,
        architecture: str,
    ) -> str:
        """Push an existing local Docker image to the registry and return its URI.

        Used when the container is cached locally but its registry URI is unknown
        (e.g., after previously cleaning resources). Computes the registry
        name, pushes the image, and returns the full image URI.

        Args:
            benchmark: Benchmark name (e.g., '110.dynamic-html')
            language_name: Programming language name (e.g., 'python')
            language_version: Language version (e.g., '3.8')
            architecture: Target architecture (e.g., 'x64')

        Returns:
            str: Full URI of the pushed image.
        """
        registry_name, repository_name, image_tag, image_uri = self.registry_name(
            benchmark, language_name, language_version, architecture
        )
        self.logging.info(
            f"Pushing Docker image {repository_name}:{image_tag} to registry: {registry_name}."
        )
        self.push_image(image_uri, image_tag)
        return image_uri

    def build_base_image(
        self,
        directory: str,
        language: Language,
        language_version: str,
        architecture: str,
        benchmark: str,
        is_cached: bool,
        builder_image: str,
    ) -> Tuple[bool, str, float]:
        """
            Build benchmark Docker image.
            When building function for the first time (according to SeBS cache),
            check if Docker image is available in the registry.
            If yes, then skip building.
            If no, then continue building.

            For every subsequent build, we rebuild image and push it to the
            registry. These are triggered by users modifying code and enforcing
            a build.

        Args:
            directory: build directory
            language: benchmark language
            language_version: benchmark language version
            architecture: CPU architecture
            benchmark: benchmark name
            is_cached: true if the image is currently cached
            builder_image: Base image for containers

        Returns:
            Tuple[bool, str, float]: True if image was rebuilt, and image URI and size in MB
        """

        registry_name, repository_name, image_tag, image_uri = self.registry_name(
            benchmark, language.value, language_version, architecture
        )

        # cached package, rebuild not enforced -> check for new one
        # if cached is true, no need to build and push the image.
        if is_cached:
            if self.find_image(repository_name, image_tag):
                self.logging.info(
                    f"Skipping building Docker image for {benchmark}, using "
                    f"Docker image {image_uri} from registry: {registry_name}."
                )
                return False, image_uri, 0.0
            else:
                # image doesn't exist, let's continue
                self.logging.info(
                    f"Image {image_uri} doesn't exist in the registry, "
                    f"building the image for {benchmark}."
                )

        build_dir = os.path.join(directory, "build")
        os.makedirs(build_dir, exist_ok=True)

        # Check if custom Dockerfile exists in directory (e.g., for C++)
        custom_dockerfile = os.path.join(directory, "Dockerfile")
        if os.path.exists(custom_dockerfile):
            shutil.move(custom_dockerfile, os.path.join(build_dir, "Dockerfile"))
        else:
            # Use template for languages without custom generation
            dockerfile_path = get_resource_path("dockerfiles")
            shutil.copy(
                os.path.join(dockerfile_path, self.name(), language.value, "Dockerfile.function"),
                os.path.join(build_dir, "Dockerfile"),
            )
        for fn in os.listdir(directory):
            if fn not in ("index.js", "__main__.py"):
                file = os.path.join(directory, fn)
                shutil.move(file, build_dir)

        with open(os.path.join(build_dir, ".dockerignore"), "w") as f:
            f.write("Dockerfile")

        base_image = self.system_config.benchmark_base_images(
            self.name(), language.value, architecture
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

        buildargs = {
            "VERSION": language_version,
            "BASE_IMAGE": base_image,
            "BASE_IMAGE_BUILDER": builder_image,
            "TARGET_ARCHITECTURE": architecture,
            "BASE_REPOSITORY": self.system_config.docker_repository(),
        }

        try:
            image, _ = self.docker_client.images.build(
                tag=image_uri, path=build_dir, buildargs=buildargs
            )
        except docker.errors.BuildError as e:
            self.logging.error("Docker build failed!")

            for chunk in e.build_log:
                if "stream" in chunk:
                    self.logging.error(chunk["stream"])
            raise e

        self.logging.info(
            f"Push the benchmark base image {repository_name}:{image_tag} "
            f"to registry: {registry_name}."
        )

        self.push_image(image_uri, image_tag)

        return True, image_uri, image.attrs["Size"] / 1024.0 / 1024.0
