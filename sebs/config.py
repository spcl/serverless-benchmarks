"""Configuration management for SeBS (Serverless Benchmarking Suite).

This module provides configuration management functionality for the SeBS framework,
including system configuration loading, Docker image management, and deployment
setting retrieval from the systems.json configuration file.

The SeBSConfig class serves as the central configuration manager that provides
access to platform-specific settings, language configurations, and deployment
options across different cloud providers and local deployments.
"""

import json
from typing import Dict, List, Optional

from sebs.utils import project_absolute_path


class SeBSConfig:
    """Central configuration manager for SeBS framework.

    This class manages all configuration settings for the SeBS benchmarking suite,
    including system configurations, Docker settings, deployment options, and
    platform-specific parameters. It loads configuration from systems.json and
    provides convenient access methods for various configuration aspects.

    Attributes:
        _system_config (Dict): The loaded system configuration from systems.json.
        _image_tag_prefix (str): Custom prefix for Docker image tags.
    """

    def __init__(self) -> None:
        """Initialize SeBSConfig by loading system configuration.

        Loads the systems.json configuration file and initializes the image tag prefix.

        Raises:
            FileNotFoundError: If systems.json configuration file is not found.
            json.JSONDecodeError: If systems.json contains invalid JSON.
        """
        with open(project_absolute_path("config", "systems.json"), "r") as cfg:
            self._system_config = json.load(cfg)
        self._image_tag_prefix = ""

    @property
    def image_tag_prefix(self) -> str:
        """Get the current Docker image tag prefix.

        Returns:
            str: The current image tag prefix.
        """
        return self._image_tag_prefix

    @image_tag_prefix.setter
    def image_tag_prefix(self, tag: str) -> None:
        """Set the Docker image tag prefix.

        Args:
            tag (str): The prefix to use for Docker image tags.
        """
        self._image_tag_prefix = tag

    def docker_repository(self) -> str:
        """Get the Docker repository name from configuration.

        Returns:
            str: The Docker repository name configured in systems.json.
        """
        return self._system_config["general"]["docker_repository"]

    def deployment_packages(self, deployment_name: str, language_name: str) -> Dict[str, str]:
        """Get deployment packages for a specific deployment and language.

        Args:
            deployment_name (str): Name of the deployment platform (e.g., 'aws', 'azure').
            language_name (str): Programming language name (e.g., 'python', 'nodejs').

        Returns:
            Dict[str, str]: Dictionary mapping package names to their versions.
        """
        return self._system_config[deployment_name]["languages"][language_name]["deployment"][
            "packages"
        ]

    def deployment_module_packages(
        self, deployment_name: str, language_name: str
    ) -> Dict[str, str]:
        """Get deployment module packages for a specific deployment and language.

        Args:
            deployment_name (str): Name of the deployment platform (e.g., 'aws', 'azure').
            language_name (str): Programming language name (e.g., 'python', 'nodejs').

        Returns:
            Dict[str, str]: Dictionary mapping module package names to their versions.
        """
        return self._system_config[deployment_name]["languages"][language_name]["deployment"][
            "module_packages"
        ]

    def deployment_files(self, deployment_name: str, language_name: str) -> List[str]:
        """Get deployment files list for a specific deployment and language.

        Args:
            deployment_name (str): Name of the deployment platform (e.g., 'aws', 'azure').
            language_name (str): Programming language name (e.g., 'python', 'nodejs').

        Returns:
            List[str]: List of required deployment files.
        """
        return self._system_config[deployment_name]["languages"][language_name]["deployment"][
            "files"
        ]

    def docker_image_types(self, deployment_name: str, language_name: str) -> List[str]:
        """Get available Docker image types for a deployment and language.

        Args:
            deployment_name (str): Name of the deployment platform (e.g., 'aws', 'azure').
            language_name (str): Programming language name (e.g., 'python', 'nodejs').

        Returns:
            List[str]: List of available Docker image types.
        """
        return self._system_config[deployment_name]["languages"][language_name]["images"]

    def supported_language_versions(
        self, deployment_name: str, language_name: str, architecture: str
    ) -> List[str]:
        """Get supported language versions for a deployment, language, and architecture.

        Args:
            deployment_name (str): Name of the deployment platform (e.g., 'aws', 'azure').
            language_name (str): Programming language name (e.g., 'python', 'nodejs').
            architecture (str): Target architecture (e.g., 'x64', 'arm64').

        Returns:
            List[str]: List of supported language versions.
        """
        languages = self._system_config.get(deployment_name, {}).get("languages", {})
        base_images = languages.get(language_name, {}).get("base_images", {})
        return list(base_images.get(architecture, {}).keys())

    def supported_architecture(self, deployment_name: str) -> List[str]:
        """Get supported architectures for a deployment platform.

        Args:
            deployment_name (str): Name of the deployment platform (e.g., 'aws', 'azure').

        Returns:
            List[str]: List of supported architectures (e.g., ['x64', 'arm64']).
        """
        return self._system_config[deployment_name]["architecture"]

    def supported_package_deployment(self, deployment_name: str) -> bool:
        """Check if package-based deployment is supported for a platform.

        Args:
            deployment_name (str): Name of the deployment platform (e.g., 'aws', 'azure').

        Returns:
            bool: True if package deployment is supported, False otherwise.
        """
        return "package" in self._system_config[deployment_name]["deployments"]

    def supported_container_deployment(self, deployment_name: str) -> bool:
        """Check if container-based deployment is supported for a platform.

        Args:
            deployment_name (str): Name of the deployment platform (e.g., 'aws', 'azure').

        Returns:
            bool: True if container deployment is supported, False otherwise.
        """
        return "container" in self._system_config[deployment_name]["deployments"]

    def benchmark_base_images(
        self, deployment_name: str, language_name: str, architecture: str
    ) -> Dict[str, str]:
        """Get base Docker images for benchmarks on a specific platform.

        Args:
            deployment_name (str): Name of the deployment platform (e.g., 'aws', 'azure').
            language_name (str): Programming language name (e.g., 'python', 'nodejs').
            architecture (str): Target architecture (e.g., 'x64', 'arm64').

        Returns:
            Dict[str, str]: Dictionary mapping language versions to base image names.
        """
        return self._system_config[deployment_name]["languages"][language_name]["base_images"][
            architecture
        ]

    def version(self) -> str:
        """Get the SeBS framework version.

        Returns:
            str: The SeBS version string, or 'unknown' if not configured.
        """
        return self._system_config["general"].get("SeBS_version", "unknown")

    def benchmark_image_name(
        self,
        system: str,
        benchmark: str,
        language_name: str,
        language_version: str,
        architecture: str,
        registry: Optional[str] = None,
    ) -> str:
        """Generate full Docker image name for a benchmark.

        Args:
            system (str): Deployment system name (e.g., 'aws', 'azure').
            benchmark (str): Benchmark name (e.g., '110.dynamic-html').
            language_name (str): Programming language name (e.g., 'python').
            language_version (str): Language version (e.g., '3.8').
            architecture (str): Target architecture (e.g., 'x64').
            registry (Optional[str]): Docker registry URL. If None, uses default repository.

        Returns:
            str: Complete Docker image name including registry and tag.
        """
        tag = self.benchmark_image_tag(
            system, benchmark, language_name, language_version, architecture
        )
        repo_name = self.docker_repository()
        if registry is not None:
            return f"{registry}/{repo_name}:{tag}"
        else:
            return f"{repo_name}:{tag}"

    def benchmark_image_tag(
        self,
        system: str,
        benchmark: str,
        language_name: str,
        language_version: str,
        architecture: str,
    ) -> str:
        """Generate Docker image tag for a benchmark.

        Creates a standardized tag format that includes system, benchmark, language,
        version, architecture, optional prefix, and SeBS version.

        Args:
            system (str): Deployment system name (e.g., 'aws', 'azure').
            benchmark (str): Benchmark name (e.g., '110.dynamic-html').
            language_name (str): Programming language name (e.g., 'python').
            language_version (str): Language version (e.g., '3.8').
            architecture (str): Target architecture (e.g., 'x64').

        Returns:
            str: Generated Docker image tag.
        """
        tag = f"function.{system}.{benchmark}.{language_name}-{language_version}-{architecture}"
        if self.image_tag_prefix:
            tag = f"{tag}-{self.image_tag_prefix}"
        sebs_version = self._system_config["general"].get("SeBS_version", "unknown")
        tag = f"{tag}-{sebs_version}"
        return tag

    def username(self, deployment_name: str, language_name: str) -> str:
        """Get the username for a specific deployment and language configuration.

        Args:
            deployment_name (str): Name of the deployment platform (e.g., 'aws', 'azure').
            language_name (str): Programming language name (e.g., 'python', 'nodejs').

        Returns:
            str: The username configured for the deployment and language combination.
        """
        return self._system_config[deployment_name]["languages"][language_name]["username"]
