# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
"""
Docker image builder for SeBS.

This module provides the main class for building and pushing
Docker images used by the SeBS benchmarking framework.
"""

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import docker
from docker.errors import BuildError, DockerException
from rich.progress import Progress, TaskID

from sebs.config import SeBSConfig
from sebs.utils import LoggingBase


class DockerImageBuilder(LoggingBase):
    """
    Manages Docker image operations for SeBS infrastructure.

    This class handles building and pushing Docker images for different deployment
    platforms, programming languages, and architectures. It supports infrastructure
    images (build, run, manage, dependencies).

    The class uses a unified approach where build() and push() operations share
    the same configuration traversal logic, only differing in the final operation.

    Attributes:
        config: SeBSConfig instance containing system configuration
        docker_client: Docker client for interacting with Docker daemon
        project_dir: Root directory of the SeBS project
        dockerfiles_dir: Directory containing Dockerfiles
    """

    def __init__(
        self,
        config: SeBSConfig,
        project_dir: Path,
        docker_client: Optional[docker.DockerClient] = None,
        verbose: bool = False,
    ):
        """
        Initialize the DockerImageBuilder.

        Args:
            config: SeBSConfig instance with system configuration
            project_dir: Root directory of the SeBS project
            docker_client: Optional Docker client instance (creates new if not provided)
            verbose: Enable verbose logging output

        Raises:
            DockerException: If Docker daemon is not accessible
        """
        super().__init__()
        if verbose:
            self._logging.setLevel(logging.DEBUG)

        self.config = config
        self.project_dir = project_dir
        self.dockerfiles_dir = os.path.join(project_dir, "dockerfiles")

        if docker_client is None:
            try:
                self.docker_client = docker.from_env()
            except DockerException as e:
                self.logging.error(f"Failed to connect to Docker daemon: {e}")
                self.logging.error(
                    "Please ensure Docker is running and you have the necessary permissions."
                )
                raise
        else:
            self.docker_client = docker_client

    def _should_use_multiplatform(
        self, system: str, image_type: str, language: Optional[str] = None
    ) -> bool:
        """Check if multi-platform build should be used for this image.

        Multi-platform builds (x64 + arm64) are only enabled for:
        - AWS platform
        - Build images only
        - Python or Node.js languages

        Args:
            system: Deployment platform (e.g., 'aws', 'gcp')
            image_type: Type of image (e.g., 'build', 'run')
            language: Programming language (e.g., 'python', 'nodejs')

        Returns:
            True if multi-platform build should be used, False otherwise
        """
        return system == "aws" and image_type == "build" and language in ["python", "nodejs"]

    def _execute_multiplatform_build(
        self,
        image_name: str,
        dockerfile: str,
        buildargs: dict,
    ) -> bool:
        """Execute multi-platform build using Docker buildx.

        Builds an image for both linux/amd64 and linux/arm64 platforms
        and pushes it as a multi-platform manifest to the registry.

        Args:
            image_name: Docker image tag
            dockerfile: path to Dockerfile
            buildargs: custom build args

        Returns:
            True if build succeeded, False otherwise
        """

        self.logging.info(f"Building multi-platform image: {image_name}")
        self.logging.info("Platforms: linux/amd64, linux/arm64")
        self.logging.debug(f"Dockerfile: {dockerfile}")
        self.logging.debug(f"Build args: {buildargs}")

        # Build buildx command
        cmd = [
            "docker",
            "buildx",
            "build",
            "--platform",
            "linux/amd64,linux/arm64",
            "--push",  # Multi-platform requires push
            "-f",
            dockerfile,
            "-t",
            image_name,
        ]

        # Add build args
        for key, value in buildargs.items():
            cmd.extend(["--build-arg", f"{key}={value}"])

        # Add context path
        cmd.append(str(self.project_dir))

        try:
            # Run buildx command
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                cwd=str(self.project_dir),
            )
            self.logging.info(f"Successfully built and pushed multi-platform image: {image_name}")
            self.logging.debug(f"Buildx output: {result.stdout}")
            return True
        except subprocess.CalledProcessError as exc:
            self.logging.error(f"Multi-platform build failed for {image_name}")
            self.logging.error(f"Exit code: {exc.returncode}")
            self.logging.error(f"Stdout: {exc.stdout}")
            self.logging.error(f"Stderr: {exc.stderr}")
            return False
        except FileNotFoundError:
            self.logging.error("docker buildx command not found")
            self.logging.error("Please ensure Docker buildx is installed")
            return False

    def _execute_build(
        self,
        system: str,
        image_type: str,
        language: Optional[str] = None,
        version: Optional[str] = None,
        version_name: Optional[str] = None,
        platform: Optional[str] = None,
        multi_platform: bool = False,
        parallel: int = 1,
    ) -> bool:
        """
        Execute the actual build operation for a single image.

        For AWS Python/Node.js build images, uses multi-platform build (x64 + arm64).
        For all other images, uses standard single-platform build.

        Args:
            system: Deployment platform
            image_type: Type of image
            language: Programming language, optional
            version: Language version, optional
            version_name: Base image name for the version, optional
            platform: Docker platform override, optional
            multi_platform: If we should build both x64 and arm64
            parallel: Number of parallel workers, default 1

        Returns:
            True if build succeeded, False otherwise
        """

        # Locate dockerfile
        if language:
            dockerfile = os.path.join(
                self.dockerfiles_dir, system, language, f"Dockerfile.{image_type}"
            )
        else:
            dockerfile = os.path.join(self.dockerfiles_dir, system, f"Dockerfile.{image_type}")

        if not os.path.exists(dockerfile):
            self.logging.warning(f"Dockerfile not found: {dockerfile}")
            return False

        # Full Docker image tag
        image_name = self.config.docker_image_name(system, image_type, language, version)

        # Prepare build args
        buildargs = {
            "VERSION": version or "",
            "WORKERS": str(parallel),
            "SEBS_VERSION": self.config.version(),
            "BASE_REPOSITORY": self.config.docker_repository(),
        }
        if version_name:
            buildargs["BASE_IMAGE"] = version_name

        # Check if multi-platform build should be used
        if multi_platform and self._should_use_multiplatform(system, image_type, language):
            if version is None or version_name is None:
                self.logging.error(
                    f"Multi-platform build not supported for {system}/{language}/{version}"
                )
                return False
            return self._execute_multiplatform_build(image_name, dockerfile, buildargs)

        # Standard single-platform build
        platform_arg = platform or os.environ.get("DOCKER_DEFAULT_PLATFORM")

        self.logging.debug(f"Building {image_name} from {dockerfile}")
        self.logging.debug(f"Build args: {buildargs}")

        try:
            self.docker_client.images.build(
                path=str(self.project_dir),
                dockerfile=dockerfile,
                buildargs=buildargs,
                tag=image_name,
                platform=platform_arg,
            )
            self.logging.info(f"Successfully built: {image_name}")
            return True
        except BuildError as exc:
            self.logging.error(f"Build failed for {image_name}")
            self.logging.error(exc)
            self.logging.debug("Build log:")
            for line in exc.build_log:
                if "stream" in line:
                    self.logging.debug(line["stream"].strip())
            return False

    def _execute_push(
        self,
        system: str,
        image_type: str,
        language: Optional[str] = None,
        version: Optional[str] = None,
        **kwargs,  # Ignore extra args like version_name, platform, parallel
    ) -> bool:
        """
        Execute the actual push operation for a single image.

        Multi-platform images (AWS Python/Node.js build images) are skipped
        as they are already pushed during the build process.

        Args:
            system: Deployment platform
            image_type: Type of image
            language: Programming language, optional
            version: Language version, optional
            **kwargs: Additional arguments (ignored for push)

        Returns:
            True if push succeeded, False otherwise
        """
        # Skip multi-platform images - they're already pushed during build
        if self._should_use_multiplatform(system, image_type, language):
            image_name = self.config.docker_image_name(system, image_type, language, version)
            self.logging.info(
                f"Skipping push for multi-platform image (already pushed): {image_name}"
            )
            return True

        # Full Docker image tag
        image_name = self.config.docker_image_name(system, image_type, language, version)

        self.logging.debug(f"Pushing {image_name}")

        try:
            # Check if image exists locally
            self.docker_client.images.get(image_name)
        except docker.errors.ImageNotFound:
            self.logging.error(f"Image not found locally: {image_name}")
            self.logging.error("Build the image first before pushing")
            return False

        try:
            # Parse image name into repository and tag
            # Format: repository:tag
            repository, tag = image_name.split(":", 1)

            DockerImageBuilder.push_image_with_progress(
                self.docker_client, repository, tag, self.logging, disable_rich_output=False
            )

            self.logging.info(f"Successfully pushed: {image_name}")
            return True
        except Exception as exc:
            self.logging.error(f"Push failed for {image_name}")
            self.logging.error(exc)
            return False

    def _process_image(
        self,
        operation: str,
        system: str,
        image_type: str,
        language: Optional[str] = None,
        version: Optional[str] = None,
        version_name: Optional[str] = None,
        platform: Optional[str] = None,
        multi_platform: bool = False,
        parallel: int = 1,
    ) -> bool:
        """
        Process a single image with the specified operation.

        Args:
            operation: Operation to perform ('build' or 'push')
            system: Deployment platform
            image_type: Type of image
            language: Programming language, optional
            version: Language version, optional
            version_name: Base image name for the version, optional
            platform: Docker platform override, optional
            multi_platform: If we should build both x64 and arm64
            parallel: Number of parallel workers, default 1

        Returns:
            True if operation succeeded, False otherwise
        """
        # Log the operation
        msg = f"{operation.capitalize()}ing *{image_type}* image for *{system}*"
        if language:
            msg += f" with language *{language}*"
        if version:
            msg += f" with version *{version}*"
        self.logging.info(msg)

        # Execute the appropriate operation
        if operation == "build":
            return self._execute_build(
                system,
                image_type,
                language,
                version,
                version_name,
                platform,
                multi_platform,
                parallel,
            )
        elif operation == "push":
            return self._execute_push(system, image_type, language, version)
        else:
            raise ValueError(f"Unknown operation: {operation}")

    def _process_language(
        self,
        operation: str,
        system: str,
        language: str,
        language_config: Dict,
        architecture: str = "x64",
        language_version: Optional[str] = None,
        image_type: Optional[str] = None,
        platform: Optional[str] = None,
        multi_platform: bool = False,
        parallel: int = 1,
    ) -> None:
        """
        Process images for a specific language with the specified operation.

        Args:
            operation: Operation to perform ('build' or 'push')
            system: Deployment platform
            language: Programming language
            language_config: Configuration dict for the language
            architecture: Target architecture (x64 or arm64), default "x64"
            language_version: Specific version to process, processes all if None
            image_type: Specific image type to process, processes all if None
            platform: Docker platform override, optional
            multi_platform: If we should build both x64 and arm64
            parallel: Number of parallel workers, default 1
        """
        # Maps to language_version and Docker base image for that version
        configs: List[Tuple[str | None, str | None]] = []
        if "base_images" in language_config:
            arch_key = architecture if architecture in language_config["base_images"] else "x64"
            if arch_key not in language_config["base_images"]:
                self.logging.warning(
                    f"Architecture {architecture} not found for {language} on {system}"
                )
                return

            for version, base_image in language_config["base_images"][arch_key].items():
                if language_version is not None and language_version != version:
                    continue
                configs.append((version, base_image))
        else:
            configs.append((None, None))

        for image_config in configs:
            # Image_type None -> we process all types (build, run)
            if image_type is None:
                for img_type in language_config["images"]:
                    self._process_image(
                        operation,
                        system,
                        img_type,
                        language,
                        *image_config,
                        platform=platform,
                        multi_platform=multi_platform,
                        parallel=parallel,
                    )
            else:
                self._process_image(
                    operation,
                    system,
                    image_type,
                    language,
                    *image_config,
                    platform=platform,
                    multi_platform=multi_platform,
                    parallel=parallel,
                )

    def _process_system(
        self,
        operation: str,
        system: str,
        system_config: Dict,
        image_type: Optional[str] = None,
        language: Optional[str] = None,
        language_version: Optional[str] = None,
        architecture: str = "x64",
        dependency_type: Optional[str] = None,
        platform: Optional[str] = None,
        multi_platform: bool = False,
        parallel: int = 1,
    ) -> None:
        """
        Process images for a specific deployment system with the specified operation.

        Args:
            operation: Operation to perform ('build' or 'push')
            system: Deployment platform
            system_config: Configuration dict for the system
            image_type: Specific image type to process, processes all if None
            language: Specific language to process, processes all if None
            language_version: Specific version to process, processes all if None
            architecture: Target architecture, default "x64"
            dependency_type: Specific dependency for cpp (opencv, boost, etc.), optional
            platform: Docker platform override, optional
            multi_platform: If we should build both x64 and arm64
            parallel: Number of parallel workers, default 1
        """
        if image_type == "manage":
            # Special case: manage image, e.g., CLI tool
            if "images" in system_config:
                self._process_image(
                    operation, system, image_type, platform=platform, parallel=parallel
                )
            else:
                self.logging.info(f"Skipping manage image for {system}")

        elif image_type == "dependencies":
            # Special case: dependencies (currently only for cpp)
            if not language:
                self.logging.error("Programming language must be specified for dependencies!")
                return
            if language not in system_config.get("languages", {}):
                self.logging.warning(f"Language {language} not found for {system}")
                return
            language_config = system_config["languages"][language]
            if "dependencies" not in language_config:
                self.logging.warning(f"No dependencies defined for {language} on {system}")
                return

            arch_key = architecture if architecture in language_config["base_images"] else "x64"
            if dependency_type:
                for version, base_image in language_config["base_images"][arch_key].items():
                    if language_version and language_version != version:
                        continue
                    self._process_image(
                        operation,
                        system,
                        f"dependencies-{dependency_type}",
                        language,
                        version,
                        base_image,
                        platform=platform,
                        multi_platform=multi_platform,
                        parallel=parallel,
                    )
            else:
                for dep in language_config["dependencies"]:
                    for version, base_image in language_config["base_images"][arch_key].items():
                        if language_version and language_version != version:
                            continue
                        self._process_image(
                            operation,
                            system,
                            f"dependencies-{dep}",
                            language,
                            version,
                            base_image,
                            platform=platform,
                            multi_platform=multi_platform,
                            parallel=parallel,
                        )
        else:
            # General case: process all or selected images for the deployment
            if language:
                # Only for selected language
                if language in system_config.get("languages", {}):
                    self._process_language(
                        operation,
                        system,
                        language,
                        system_config["languages"][language],
                        architecture=architecture,
                        language_version=language_version,
                        image_type=image_type,
                        platform=platform,
                        multi_platform=multi_platform,
                        parallel=parallel,
                    )
                else:
                    self.logging.warning(f"Language {language} not found for {system}")
            else:
                # No filters - process all languages supported on the platform
                for lang, lang_dict in system_config.get("languages", {}).items():
                    self._process_language(
                        operation,
                        system,
                        lang,
                        lang_dict,
                        architecture=architecture,
                        language_version=language_version,
                        image_type=image_type,
                        platform=platform,
                        multi_platform=multi_platform,
                        parallel=parallel,
                    )
                # No filters - process additional image types supported on the platform
                if "images" in system_config:
                    for img_type, _ in system_config["images"].items():
                        self._process_image(
                            operation,
                            system,
                            img_type,
                            platform=platform,
                            multi_platform=multi_platform,
                            parallel=parallel,
                        )

    def _process(
        self,
        operation: str,
        deployment: Optional[str] = None,
        image_type: Optional[str] = None,
        language: Optional[str] = None,
        language_version: Optional[str] = None,
        architecture: str = "x64",
        dependency_type: Optional[str] = None,
        platform: Optional[str] = None,
        multi_platform: bool = False,
        parallel: int = 1,
    ) -> None:
        """
        Main processing method for build and push operations.

        This method traverses the configuration hierarchy and applies the specified
        operation (build or push) to matching images.

        Args:
            operation: Operation to perform ('build' or 'push')
            deployment: Specific platform to process, processes all if None
            image_type: Specific image type, processes all if None
            language: Specific language, processes all if None
            language_version: Specific version, processes all if None
            architecture: Target architecture, default "x64"
            dependency_type: Specific dependency for cpp, optional
            platform: Docker platform override, optional
            multi_platform: If we should build both x64 and arm64
            parallel: Number of parallel workers, default 1
        """
        systems_config = self.config._system_config

        if deployment:
            if deployment in systems_config:
                self._process_system(
                    operation,
                    deployment,
                    systems_config[deployment],
                    image_type=image_type,
                    language=language,
                    language_version=language_version,
                    architecture=architecture,
                    dependency_type=dependency_type,
                    platform=platform,
                    multi_platform=multi_platform,
                    parallel=parallel,
                )
            else:
                self.logging.error(f"Unknown deployment: {deployment}")
        else:
            for system, system_dict in systems_config.items():
                self._process_system(
                    operation,
                    system,
                    system_dict,
                    image_type=image_type,
                    language=language,
                    language_version=language_version,
                    architecture=architecture,
                    dependency_type=dependency_type,
                    platform=platform,
                    multi_platform=multi_platform,
                    parallel=parallel,
                )

    def build(
        self,
        deployment: Optional[str] = None,
        image_type: Optional[str] = None,
        language: Optional[str] = None,
        language_version: Optional[str] = None,
        architecture: str = "x64",
        dependency_type: Optional[str] = None,
        platform: Optional[str] = None,
        multi_platform: bool = False,
        parallel: int = 1,
    ) -> None:
        """
        Build Docker images for SeBS infrastructure.

        This is the main entry point for building images. It can build:
        - All images for all platforms (no filters)
        - All images for a specific platform (deployment filter)
        - Specific image types (image_type filter)
        - Specific languages and versions (language filters)

        Args:
            deployment: Specific platform to build for, builds all if None
            image_type: Specific image type, builds all if None
            language: Specific language, builds all if None
            language_version: Specific version, builds all if None
            architecture: Target architecture, default "x64"
            dependency_type: Specific dependency for cpp, optional
            platform: Docker platform override, optional
            multi_platform: If we should build both x64 and arm64
            parallel: Number of parallel workers, default 1
        """
        self._process(
            operation="build",
            deployment=deployment,
            image_type=image_type,
            language=language,
            language_version=language_version,
            architecture=architecture,
            dependency_type=dependency_type,
            platform=platform,
            multi_platform=multi_platform,
            parallel=parallel,
        )

    def push(
        self,
        deployment: Optional[str] = None,
        image_type: Optional[str] = None,
        language: Optional[str] = None,
        language_version: Optional[str] = None,
        architecture: str = "x64",
        dependency_type: Optional[str] = None,
    ) -> None:
        """
        Push Docker images to registry.

        This is the main entry point for pushing images. It can push:
        - All images for all platforms (no filters)
        - All images for a specific platform (deployment filter)
        - Specific image types (image_type filter)
        - Specific languages and versions (language filters)

        Args:
            deployment: Specific platform to push for, pushes all if None
            image_type: Specific image type, pushes all if None
            language: Specific language, pushes all if None
            language_version: Specific version, pushes all if None
            architecture: Target architecture, default "x64"
            dependency_type: Specific dependency for cpp, optional
        """
        self._process(
            operation="push",
            deployment=deployment,
            image_type=image_type,
            language=language,
            language_version=language_version,
            architecture=architecture,
            dependency_type=dependency_type,
        )

    @staticmethod
    def show_progress(txt: str, progress: Progress, layer_tasks: Dict[str, TaskID]):
        """Update progress display for Docker operations.

        Parses Docker API output and updates the rich progress display for
        operations like image pushing. Tracks individual layer progress and
        handles completion events.

        This is a static utility method that can be used by other modules
        for consistent progress display across SeBS.

        Args:
            txt: Docker API output line (JSON string or dict)
            progress: Rich progress instance to update
            layer_tasks: Dictionary tracking progress tasks for each layer

        Raises:
            Exception: If an error is reported in the Docker output
        """
        if isinstance(txt, str):
            line = json.loads(txt)
        else:
            line = txt

        status = line.get("status", "")
        progress_detail = line.get("progressDetail", {})
        id_ = line.get("id", "")

        if "Pushing" in status and progress_detail:
            current = progress_detail.get("current", 0)
            total = progress_detail.get("total", 0)

            if id_ not in layer_tasks and total > 0:
                # Create new progress task for this layer
                description = f"Layer {id_[:12]}"
                layer_tasks[id_] = progress.add_task(description, total=total)
            if id_ in layer_tasks:
                # Update progress for existing task
                progress.update(layer_tasks[id_], completed=current)

        elif any(x in status for x in ["Layer already exists", "Pushed"]):
            if id_ in layer_tasks:
                # Complete the task
                progress.update(layer_tasks[id_], completed=progress.tasks[layer_tasks[id_]].total)

        elif "error" in line:
            raise Exception(line["error"])

    @staticmethod
    def push_image_with_progress(
        docker_client: docker.DockerClient,
        repository_uri: str,
        image_tag: str,
        logger,
        disable_rich_output: bool = False,
    ):
        """Push a Docker image to a container registry with progress tracking.

        This is a static utility method that provides a consistent interface
        for pushing Docker images with optional rich progress bars. It can
        be used by any module in SeBS that needs to push images.

        Args:
            docker_client: Docker client for container operations
            repository_uri: URI of the container registry repository
            image_tag: Tag of the image to push
            logger: Logger instance for output messages
            disable_rich_output: If True, disable rich progress bars

        Raises:
            docker.errors.APIError: If the push operation fails
            RuntimeError: If an error occurs during the push stream
        """
        try:
            if not disable_rich_output:
                layer_tasks: Dict[str, TaskID] = {}
                with Progress() as progress:
                    logger.info(f"Pushing image {image_tag} to {repository_uri}")
                    ret = docker_client.images.push(
                        repository=repository_uri,
                        tag=image_tag,
                        stream=True,
                        decode=True,
                    )
                    for line in ret:
                        DockerImageBuilder.show_progress(line, progress, layer_tasks)

            else:
                logger.info(f"Pushing image {image_tag} to {repository_uri}")
                ret = docker_client.images.push(
                    repository=repository_uri, tag=image_tag, stream=True, decode=True
                )

                for val in ret:
                    if "error" in val:
                        logger.error(f"Failed to push the image to registry {repository_uri}")
                        raise RuntimeError(val)

        except docker.errors.APIError as e:
            logger.error(f"Failed to push the image to registry {repository_uri}. Error: {str(e)}")
            raise e
