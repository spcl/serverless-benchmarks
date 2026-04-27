import atexit
import io
import logging
import os
import tarfile
import threading
from typing import Optional

import docker

from sebs.config import SeBSConfig
from sebs.utils import LoggingBase


class CloudflareCLI(LoggingBase):
    """
    Manages a Docker container with Cloudflare Wrangler and related tools pre-installed.

    This approach isolates Cloudflare CLI tools (wrangler, pywrangler) from the host system,
    avoiding global npm/uv installations and ensuring consistent behavior across platforms.
    """

    _instance: Optional["CloudflareCLI"] = None
    _lock: threading.Lock = threading.Lock()

    @staticmethod
    def get_instance(system_config: SeBSConfig, docker_client: docker.client) -> "CloudflareCLI":
        """Return the shared CloudflareCLI instance, creating it on first use.

        Container and native workers deployments share one underlying CLI
        container so that combined runs don't spawn duplicates.
        Thread-safe: the first caller builds the container; concurrent callers wait.
        """
        if CloudflareCLI._instance is None:
            with CloudflareCLI._lock:
                if CloudflareCLI._instance is None:
                    CloudflareCLI._instance = CloudflareCLI(system_config, docker_client)
                    atexit.register(CloudflareCLI.shutdown_instance)
        return CloudflareCLI._instance

    def __init__(self, system_config: SeBSConfig, docker_client: docker.client):
        super().__init__()
        self._stopped = False

        repo_name = system_config.docker_repository()
        image_name = "manage.cloudflare"
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

        # Start the container in detached mode
        self.docker_instance = docker_client.containers.run(
            image=repo_name + ":" + image_name,
            command="/bin/bash",
            environment={
                "CONTAINER_UID": str(os.getuid()),
                "CONTAINER_GID": str(os.getgid()),
                "CONTAINER_USER": "docker_user",
            },
            volumes={
                # Mount Docker socket so wrangler can build and push images to
                # Cloudflare's registry during `wrangler deploy` for container workers.
                "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"}
            },
            remove=True,
            stdout=True,
            stderr=True,
            detach=True,
            tty=True,
        )

        self.logging.info(f"Started Cloudflare CLI container: {self.docker_instance.id}.")

        # Wait for container to be ready
        while True:
            try:
                dkg = self.docker_instance.logs(stream=True, follow=True)
                next(dkg).decode("utf-8")
                break
            except StopIteration:
                pass

    @staticmethod
    def typename() -> str:
        return "Cloudflare.CLI"

    def execute(self, cmd: str, env: Optional[dict] = None):
        """
        Execute the given command in Cloudflare CLI container.
        Throws an exception on failure (commands are expected to execute successfully).

        Args:
            cmd: Shell command to execute
            env: Optional environment variables dict

        Returns:
            Command output as bytes
        """
        # Wrap command in sh -c to support shell features like cd, pipes, etc.
        shell_cmd = ["/bin/sh", "-c", cmd]
        exit_code, out = self.docker_instance.exec_run(
            shell_cmd,
            # Run as root since entrypoint creates docker_user but we don't wait for it
            user="root",
            environment=env,
        )
        if exit_code != 0:
            raise RuntimeError(
                "Command {} failed at Cloudflare CLI docker!\n Output {}".format(
                    cmd, out.decode("utf-8")
                )
            )
        return out

    def upload_package(self, directory: str, dest: str):
        """
        Upload a directory to the Docker container.

        This is not an efficient and memory-intensive implementation.
        So far, we didn't have very large functions that require many gigabytes.

        Since docker-py does not support a straightforward copy, and we can't
        put_archive in chunks.

        Args:
            directory: Local directory to upload
            dest: Destination path in container
        """
        handle = io.BytesIO()
        with tarfile.open(fileobj=handle, mode="w:gz") as tar:
            for f in os.listdir(directory):
                tar.add(os.path.join(directory, f), arcname=f)

        # Move to the beginning of memory before writing
        handle.seek(0)
        self.execute("mkdir -p {}".format(dest))
        self.docker_instance.put_archive(path=dest, data=handle.read())

    def check_wrangler_version(self) -> str:
        """
        Check wrangler version.

        Returns:
            Version string
        """
        out = self.execute("wrangler --version")
        return out.decode("utf-8").strip()

    def check_pywrangler_version(self) -> str:
        """
        Check pywrangler version.

        Returns:
            Version string
        """
        out = self.execute("pywrangler --version")
        return out.decode("utf-8").strip()

    def containers_push(self, tag: str, env: Optional[dict] = None) -> str:
        """
        Push a locally-built image to Cloudflare's container registry.

        The image must already exist locally (built by docker_client.images.build).
        The manage container shares the host Docker socket, so it can see and push
        local images directly.

        Args:
            tag: Local image tag (e.g. my-bench-python-312:latest)
            env: Environment variables (must include CLOUDFLARE_API_TOKEN and
                 CLOUDFLARE_ACCOUNT_ID)

        Returns:
            Registry URI (registry.cloudflare.com/<account>/<image>:<tag>)
        """
        out = self.execute(f"wrangler containers push {tag}", env=env)
        output = out.decode("utf-8")
        for line in output.splitlines():
            if "registry.cloudflare.com" in line:
                parts = line.split()
                for part in parts:
                    if part.startswith("registry.cloudflare.com"):
                        return part.strip()
        raise RuntimeError(
            f"Could not parse registry URI from wrangler containers push output:\n{output}"
        )

    def wrangler_deploy(self, package_dir: str, env: Optional[dict] = None) -> str:
        """
        Deploy a worker using wrangler.

        Args:
            package_dir: Path to package directory in container
            env: Environment variables for deployment

        Returns:
            Deployment output
        """
        cmd = "cd {} && npm install && wrangler deploy".format(package_dir)
        out = self.execute(cmd, env=env)
        return out.decode("utf-8")

    def pywrangler_deploy(self, package_dir: str, env: Optional[dict] = None) -> str:
        """
        Deploy a Python worker using pywrangler.

        Args:
            package_dir: Path to package directory in container
            env: Environment variables for deployment

        Returns:
            Deployment output
        """
        cmd = "cd {} && pywrangler deploy".format(package_dir)
        out = self.execute(cmd, env=env)
        return out.decode("utf-8")

    @staticmethod
    def shutdown_instance():
        """Stop the shared CLI container and clear the singleton.

        Call this once at process teardown, after all parallel benchmarks
        have finished.  Individual deployment handlers must NOT call this —
        they should just drop their local reference.
        """
        with CloudflareCLI._lock:
            instance = CloudflareCLI._instance
            CloudflareCLI._instance = None

        if instance is not None and not instance._stopped:
            instance._stopped = True
            instance.logging.info("Stopping Cloudflare CLI Docker instance")
            instance.docker_instance.stop()
