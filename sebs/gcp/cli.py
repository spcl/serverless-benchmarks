import logging
import os

import docker

from sebs.config import SeBSConfig
from sebs.gcp.config import GCPCredentials
from sebs.utils import LoggingBase


class GCloudCLI(LoggingBase):
    """
    Manages interactions with Google Cloud CLI (gcloud) through a Docker container.

    This class starts a Docker container running the gcloud CLI, allowing for
    execution of gcloud commands, authentication, and other operations.
    """
    @staticmethod
    def typename() -> str:
        """Return the type name of this class."""
        return "GCP.CLI"

    def __init__(
        self, credentials: GCPCredentials, system_config: SeBSConfig, docker_client: docker.client
    ):
        """
        Initialize GCloudCLI and start the Docker container.

        Pulls the gcloud CLI Docker image if not found locally, then runs a
        container in detached mode with credentials mounted.

        :param credentials: GCPCredentials object containing the path to service account JSON file.
        :param system_config: SeBS system configuration.
        :param docker_client: Docker client instance.
        :raises RuntimeError: If Docker image pull fails.
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
        """
        Execute a command in the gcloud CLI Docker container.

        :param cmd: The command string to execute.
        :return: The standard output of the command as bytes.
        :raises RuntimeError: If the command execution fails (non-zero exit code).
        """
        exit_code, out = self.docker_instance.exec_run(cmd)
        if exit_code != 0:
            raise RuntimeError(
                "Command {} failed at gcloud CLI docker!\n Output {}".format(
                    cmd, out.decode("utf-8")
                )
            )
        return out

    def login(self, project_name: str):
        """
        Log in to gcloud CLI using a service account and set the project.

        Authenticates using the mounted credentials file (`/credentials.json` in
        the container) and then sets the active Google Cloud project.
        Handles potential interactive prompts when setting the project by passing "Y".

        Important:
            - `gcloud init` is not used as it requires browser-based authentication.
            - Setting the project might show warnings about Cloud Resource Manager API
              permissions, which are generally not needed for SeBS operations.

        :param project_name: The Google Cloud project name/ID to set as active.
        """
        self.execute("gcloud auth login --cred-file=/credentials.json")
        # Pass "Y" to confirm setting the project if prompted, especially if APIs are not enabled.
        self.execute(f"/bin/bash -c 'gcloud config set project {project_name} <<< Y'")
        self.logging.info("gcloud CLI login succesful")

    def shutdown(self):
        """Stop the gcloud CLI Docker container."""
        self.logging.info("Stopping gcloud CLI manage Docker instance")
        self.docker_instance.stop()
