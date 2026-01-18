import io
import logging
import os
import tarfile

import docker

from sebs.config import SeBSConfig
from sebs.utils import LoggingBase


class CloudflareCLI(LoggingBase):
    """
    Manages a Docker container with Cloudflare Wrangler and related tools pre-installed.
    
    This approach isolates Cloudflare CLI tools (wrangler, pywrangler) from the host system,
    avoiding global npm/uv installations and ensuring consistent behavior across platforms.
    """

    def __init__(self, system_config: SeBSConfig, docker_client: docker.client):
        super().__init__()

        repo_name = system_config.docker_repository()
        image_name = "manage.cloudflare"
        full_image_name = repo_name + ":" + image_name
        
        # Try to get the image, pull if not found, build if pull fails
        try:
            docker_client.images.get(full_image_name)
            logging.info(f"Using existing Docker image: {full_image_name}")
        except docker.errors.ImageNotFound:
            # Try to pull the image first
            try:
                logging.info(f"Pulling Docker image {full_image_name}...")
                docker_client.images.pull(repo_name, image_name)
                logging.info(f"Successfully pulled {full_image_name}")
            except docker.errors.APIError as pull_error:
                # If pull fails, try to build the image locally
                logging.info(f"Pull failed: {pull_error}. Building image locally...")
                
                # Find the Dockerfile path
                dockerfile_path = os.path.join(
                    os.path.dirname(__file__), 
                    "..", 
                    "..", 
                    "dockerfiles", 
                    "cloudflare", 
                    "Dockerfile.manage"
                )
                
                if not os.path.exists(dockerfile_path):
                    raise RuntimeError(
                        f"Dockerfile not found at {dockerfile_path}. "
                        "Cannot build Cloudflare CLI container."
                    )
                
                # Build the image
                build_path = os.path.join(os.path.dirname(__file__), "..", "..")
                logging.info(f"Building {full_image_name} from {dockerfile_path}...")
                
                try:
                    image, build_logs = docker_client.images.build(
                        path=build_path,
                        dockerfile=dockerfile_path,
                        tag=full_image_name,
                        rm=True,
                        pull=True
                    )
                    
                    # Log build output
                    for log in build_logs:
                        if 'stream' in log:
                            logging.debug(log['stream'].strip())
                    
                    logging.info(f"Successfully built {full_image_name}")
                except docker.errors.BuildError as build_error:
                    raise RuntimeError(
                        f"Failed to build Docker image {full_image_name}: {build_error}"
                    )
        
        # Start the container in detached mode
        self.docker_instance = docker_client.containers.run(
            image=full_image_name,
            command="/bin/bash",
            environment={
                "CONTAINER_UID": str(os.getuid()),
                "CONTAINER_GID": str(os.getgid()),
                "CONTAINER_USER": "docker_user",
            },
            volumes={
                # Mount Docker socket for wrangler container deployments
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

    def execute(self, cmd: str, env: dict = None):
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
            user="root",  # Run as root since entrypoint creates docker_user but we don't wait for it
            environment=env
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

    def wrangler_deploy(self, package_dir: str, env: dict = None) -> str:
        """
        Deploy a worker using wrangler.
        
        Args:
            package_dir: Path to package directory in container
            env: Environment variables for deployment
            
        Returns:
            Deployment output
        """
        cmd = "cd {} && wrangler deploy".format(package_dir)
        out = self.execute(cmd, env=env)
        return out.decode("utf-8")

    def pywrangler_deploy(self, package_dir: str, env: dict = None) -> str:
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

    def npm_install(self, package_dir: str) -> str:
        """
        Run npm install in a directory.
        
        Args:
            package_dir: Path to package directory in container
            
        Returns:
            npm output
        """
        cmd = "cd {} && npm install".format(package_dir)
        out = self.execute(cmd)
        return out.decode("utf-8")

    def docker_build(self, package_dir: str, image_tag: str) -> str:
        """
        Build a Docker image for container deployment.
        
        Args:
            package_dir: Path to package directory in container
            image_tag: Tag for the Docker image
            
        Returns:
            Docker build output
        """
        cmd = "cd {} && docker build --no-cache -t {} .".format(package_dir, image_tag)
        out = self.execute(cmd)
        return out.decode("utf-8")

    def shutdown(self):
        """Shutdown Docker instance."""
        self.logging.info("Stopping Cloudflare CLI Docker instance")
        self.docker_instance.stop()
