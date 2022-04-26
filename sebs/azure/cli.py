import io
import logging
import os
import tarfile

import docker

from sebs.config import SeBSConfig


class AzureCLI:
    def __init__(self, system_config: SeBSConfig, docker_client: docker.client):
        repo_name = system_config.docker_repository()
        image_name = "manage.azure"
        try:
            docker_client.images.get(repo_name + ":" + image_name)
        except docker.errors.ImageNotFound:
            try:
                logging.info(
                    "Docker pull of image {repo}:{image}".format(
                        repo=repo_name, image=image_name
                    )
                )
                docker_client.images.pull(repo_name, image_name)
            except docker.errors.APIError:
                raise RuntimeError("Docker pull of image {} failed!".format(image_name))
        self.docker_instance = docker_client.containers.run(
            image=repo_name + ":" + image_name,
            command="/bin/bash",
            user="1000:1000",
            volumes={},
            # remove=True,
            stdout=True,
            stderr=True,
            detach=True,
            tty=True,
        )
        logging.info("Starting Azure manage Docker instance")

    """
        Execute the given command in Azure CLI.
        Throws an exception on failure (commands are expected to execute succesfully).
    """

    def execute(self, cmd: str):
        exit_code, out = self.docker_instance.exec_run(cmd, user="docker_user")
        if exit_code != 0:
            raise RuntimeError(
                "Command {} failed at Azure CLI docker!\n Output {}".format(
                    cmd, out.decode("utf-8")
                )
            )
        return out

    """
        Run azure login command on Docker instance.
    """

    def login(self, appId: str, tenant: str, password: str):
        self.execute(
            "az login -u {0} --service-principal --tenant {1} -p {2}".format(
                appId,
                tenant,
                password,
            )
        )
        logging.info("Azure login succesful")

    def upload_package(self, directory: str, dest: str):
        handle = io.BytesIO()
        with tarfile.open(fileobj=handle, mode="w:gz") as tar:
            for f in os.listdir(directory):
                tar.add(os.path.join(directory, f), arcname=f)
        # move to the beginning of memory before writing
        handle.seek(0)
        self.execute("mkdir -p {}".format(dest))
        self.docker_instance.put_archive(path=dest, data=handle.read())

    """
        Shutdowns Docker instance.
    """

    def shutdown(self):
        logging.info("Stopping Azure manage Docker instance")
        self.docker_instance.stop()
