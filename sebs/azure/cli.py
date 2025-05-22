import io
import logging
import os
import tarfile

import docker

from sebs.config import SeBSConfig
from sebs.utils import LoggingBase


class AzureCLI(LoggingBase):
    """
    Manages interactions with Azure CLI through a Docker container.

    This class starts a Docker container running the Azure CLI, allowing for
    execution of Azure commands, login, and package uploads.
    """
    def __init__(self, system_config: SeBSConfig, docker_client: docker.client):
        """
        Initialize AzureCLI and start the Docker container.

        Pulls the Azure CLI Docker image if not found locally, then runs a
        container in detached mode.

        :param system_config: SeBS system configuration.
        :param docker_client: Docker client instance.
        :raises RuntimeError: If Docker image pull fails.
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
        self._insights_installed = False
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
        """Return the type name of this class."""
        return "Azure.CLI"

    def execute(self, cmd: str) -> bytes:
        """
        Execute a command in the Azure CLI Docker container.

        :param cmd: The command string to execute.
        :return: The standard output of the command as bytes.
        :raises RuntimeError: If the command execution fails (non-zero exit code).
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
        """
        Log in to Azure using service principal credentials.

        Executes `az login` within the Docker container.

        :param appId: Application ID of the service principal.
        :param tenant: Tenant ID.
        :param password: Password/secret of the service principal.
        :return: The output of the login command.
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

    def upload_package(self, directory: str, dest: str):
        """
        Upload a directory as a tar.gz archive to the Azure CLI Docker container.

        This implementation reads the entire tar.gz archive into memory before
        uploading. This is not efficient for very large function packages.
        Potential solutions for large archives include:
        1. Manually calling `docker cp` and decompressing within the container.
        2. Committing the Docker container and restarting with a new mount volume.

        :param directory: Path to the local directory to upload.
        :param dest: Destination path within the Docker container.
        """
        handle = io.BytesIO()
        with tarfile.open(fileobj=handle, mode="w:gz") as tar:
            for f in os.listdir(directory):
                tar.add(os.path.join(directory, f), arcname=f)
        # move to the beginning of memory before writing
        handle.seek(0)
        self.execute("mkdir -p {}".format(dest))
        self.docker_instance.put_archive(path=dest, data=handle.read())

    def install_insights(self):
        """Install the Application Insights extension for Azure CLI if not already installed."""
        if not self._insights_installed:
            self.execute("az extension add --name application-insights")
            self._insights_installed = True

    def shutdown(self):
        """Stop the Azure CLI Docker container."""
        self.logging.info("Stopping Azure manage Docker instance")
        self.docker_instance.stop()
