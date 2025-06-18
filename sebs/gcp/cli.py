"""Google Cloud CLI integration for SeBS.

This module provides a Docker-based Google Cloud CLI interface for performing
administrative operations that require the gcloud command-line tool. It manages
a containerized gcloud environment with proper authentication and project setup.

Classes:
    GCloudCLI: Docker-based gcloud CLI interface for GCP operations

Example:
    Using the gcloud CLI interface:
    
        cli = GCloudCLI(credentials, system_config, docker_client)
        cli.login(project_name)
        result = cli.execute("gcloud functions list")
        cli.shutdown()
"""

import logging
import os
from typing import Union

import docker

from sebs.config import SeBSConfig
from sebs.gcp.config import GCPCredentials
from sebs.utils import LoggingBase


class GCloudCLI(LoggingBase):
    """Docker-based Google Cloud CLI interface.
    
    Provides a containerized environment for executing gcloud commands with
    proper authentication and project configuration. Uses a Docker container
    with the gcloud CLI pre-installed and configured.
    
    Attributes:
        docker_instance: Running Docker container with gcloud CLI
    """
    @staticmethod
    def typename() -> str:
        """Get the type name for this CLI implementation.
        
        Returns:
            Type name string for GCP CLI
        """
        return "GCP.CLI"

    def __init__(
        self, credentials: GCPCredentials, system_config: SeBSConfig, docker_client: docker.client
    ) -> None:
        """Initialize the gcloud CLI Docker container.
        
        Sets up a Docker container with the gcloud CLI, pulling the image if needed
        and mounting the GCP credentials file for authentication.
        
        Args:
            credentials: GCP credentials with service account file path
            system_config: SeBS system configuration
            docker_client: Docker client for container management
            
        Raises:
            RuntimeError: If Docker image pull fails
        """

        super().__init__()

        repo_name = system_config.docker_repository()
        image_name = "manage.gcp"
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

        volumes = {
            os.path.abspath(credentials.gcp_credentials): {
                "bind": "/credentials.json",
                "mode": "ro",
            }
        }
        self.docker_instance = docker_client.containers.run(
            image=repo_name + ":" + image_name,
            volumes=volumes,
            remove=True,
            stdout=True,
            stderr=True,
            detach=True,
            tty=True,
        )
        self.logging.info(f"Started gcloud CLI container: {self.docker_instance.id}.")
        # while True:
        #    try:
        #        dkg = self.docker_instance.logs(stream=True, follow=True)
        #        next(dkg).decode("utf-8")
        #        break
        #    except StopIteration:
        #        pass

    def execute(self, cmd: str) -> bytes:
        """Execute a command in the gcloud CLI container.
        
        Args:
            cmd: Command string to execute in the container
            
        Returns:
            Command output as bytes
            
        Raises:
            RuntimeError: If the command fails (non-zero exit code)
        """
        exit_code, out = self.docker_instance.exec_run(cmd)
        if exit_code != 0:
            raise RuntimeError(
                "Command {} failed at gcloud CLI docker!\n Output {}".format(
                    cmd, out.decode("utf-8")
                )
            )
        return out

    def login(self, project_name: str) -> None:
        """Authenticate gcloud CLI and set the active project.
        
        Performs service account authentication using the mounted credentials file
        and sets the specified project as the active project. Automatically confirms
        any prompts that may appear during project setup.
        
        Args:
            project_name: GCP project ID to set as active
            
        Note:
            Uses service account authentication instead of browser-based auth.
            May show warnings about Cloud Resource Manager API permissions.
        """
        self.execute("gcloud auth login --cred-file=/credentials.json")
        self.execute(f"/bin/bash -c 'gcloud config set project {project_name} <<< Y'")
        self.logging.info("gcloud CLI login succesful")

    def shutdown(self) -> None:
        """Shutdown the gcloud CLI Docker container.
        
        Stops and removes the Docker container used for gcloud operations.
        """
        self.logging.info("Stopping gcloud CLI manage Docker instance")
        self.docker_instance.stop()
