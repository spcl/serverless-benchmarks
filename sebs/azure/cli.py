"""Azure CLI Docker container management for SeBS benchmarking.

This module provides a wrapper around the Azure CLI running in a Docker container.
It handles container lifecycle, command execution, file uploads, and Azure-specific
operations required for serverless function deployment and management.

The AzureCLI class manages a Docker container with Azure CLI tools and provides
methods for executing Azure commands, uploading function packages, and handling
authentication.

Example:
    Basic usage for Azure CLI operations:
    
    ```python
    from sebs.azure.cli import AzureCLI
    
    # Initialize CLI container
    cli = AzureCLI(system_config, docker_client)
    
    # Login to Azure
    cli.login(app_id, tenant, password)
    
    # Execute Azure CLI commands
    result = cli.execute("az group list")
    
    # Upload function package
    cli.upload_package(local_dir, container_dest)
    ```
"""

import io
import logging
import os
import tarfile
from typing import Optional

import docker

from sebs.config import SeBSConfig
from sebs.utils import LoggingBase


class AzureCLI(LoggingBase):
    """Azure CLI Docker container wrapper.

    This class manages a Docker container running Azure CLI tools and provides
    methods for executing Azure commands, handling authentication, and managing
    file transfers for serverless function deployment.

    Attributes:
        docker_instance: Docker container running Azure CLI
        _insights_installed: Flag indicating if Application Insights extension is installed
    """

    def __init__(self, system_config: SeBSConfig, docker_client: docker.client) -> None:
        """Initialize Azure CLI container.

        Creates and starts a Docker container with Azure CLI tools installed.
        Handles image pulling if not available locally.

        Args:
            system_config: SeBS system configuration
            docker_client: Docker client for container operations

        Raises:
            RuntimeError: If Docker image pull fails.
        """
        super().__init__()

        repo_name = system_config.docker_repository()
        image_name = "manage.azure"
        try:
            docker_client.images.get(repo_name + ":" + image_name)
        except docker.errors.ImageNotFound:
            try:
                logging.info(
                    "Docker pull of image {repo}:{image}".format(repo=repo_name, image=image_name)
                )
                docker_client.images.pull(repo_name, image_name)
            except docker.errors.APIError:
                raise RuntimeError("Docker pull of image {} failed!".format(image_name))
        self.docker_instance = docker_client.containers.run(
            image=repo_name + ":" + image_name,
            command="/bin/bash",
            environment={
                "CONTAINER_UID": str(os.getuid()),
                "CONTAINER_GID": str(os.getgid()),
                "CONTAINER_USER": "docker_user",
            },
            remove=True,
            stdout=True,
            stderr=True,
            detach=True,
            tty=True,
        )
        self._insights_installed: bool = False
        self.logging.info(f"Started Azure CLI container: {self.docker_instance.id}.")
        while True:
            try:
                dkg = self.docker_instance.logs(stream=True, follow=True)
                next(dkg).decode("utf-8")
                break
            except StopIteration:
                pass

    @staticmethod
    def typename() -> str:
        """Get the CLI type name.

        Returns:
            Type identifier for Azure CLI.
        """
        return "Azure.CLI"

    def execute(self, cmd: str) -> bytes:
        """Execute Azure CLI command in Docker container.

        Executes the given command in the Azure CLI container and returns
        the output. Raises an exception if the command fails.

        Args:
            cmd: Azure CLI command to execute

        Returns:
            Command output as bytes.

        Raises:
            RuntimeError: If command execution fails.
        """
        exit_code, out = self.docker_instance.exec_run(cmd, user="docker_user")
        if exit_code != 0:
            raise RuntimeError(
                "Command {} failed at Azure CLI docker!\n Output {}".format(
                    cmd, out.decode("utf-8")
                )
            )
        return out

    def login(self, appId: str, tenant: str, password: str) -> bytes:
        """Login to Azure using service principal credentials.

        Authenticates with Azure using service principal credentials
        within the Docker container.

        Args:
            appId: Azure application (client) ID
            tenant: Azure tenant (directory) ID
            password: Azure client secret

        Returns:
            Login command output as bytes.
        """
        result = self.execute(
            "az login -u {0} --service-principal --tenant {1} -p {2}".format(
                appId,
                tenant,
                password,
            )
        )
        self.logging.info("Azure login succesful")
        return result

    def upload_package(self, directory: str, dest: str) -> None:
        """Upload function package to Docker container.

        Creates a compressed archive of the function package and uploads
        it to the specified destination in the Docker container.

        Note:
            This implementation loads the entire archive into memory,
            which may not be efficient for very large function packages.
            For large packages, consider using docker cp directly.

        Args:
            directory: Local directory containing function package
            dest: Destination path in the Docker container
        """
        handle = io.BytesIO()
        with tarfile.open(fileobj=handle, mode="w:gz") as tar:
            for f in os.listdir(directory):
                tar.add(os.path.join(directory, f), arcname=f)
        # move to the beginning of memory before writing
        handle.seek(0)
        self.execute("mkdir -p {}".format(dest))
        self.docker_instance.put_archive(path=dest, data=handle.read())

    def install_insights(self) -> None:
        """Install Azure Application Insights CLI extension.

        Installs the Application Insights extension for Azure CLI
        if not already installed. Required for metrics collection.
        """
        if not self._insights_installed:
            self.execute("az extension add --name application-insights")
            self._insights_installed = True

    def shutdown(self) -> None:
        """Shutdown Azure CLI Docker container.

        Stops and removes the Docker container running Azure CLI tools.
        """
        self.logging.info("Stopping Azure manage Docker instance")
        self.docker_instance.stop()
