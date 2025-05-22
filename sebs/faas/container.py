from abc import abstractmethod
import docker
import json
import platform
import os
import shutil
from typing import Tuple

from rich.progress import Progress

from sebs.config import SeBSConfig
from sebs.utils import LoggingBase, execute, DOCKER_DIR


class DockerContainer(LoggingBase):
    """
    Abstract base class for managing Docker container images for FaaS deployments.

    Provides functionalities for finding, building, and pushing Docker images
    to container registries. Specific FaaS providers should subclass this to
    implement provider-specific details like registry naming.
    """
    @staticmethod
    @abstractmethod
    def name() -> str:
        """
        Return the name of the FaaS platform this container manager is for (e.g., "aws", "azure").

        :return: Name of the FaaS platform.
        """
        pass

    @property
    def disable_rich_output(self) -> bool:
        """Flag to disable rich progress bar output during image push."""
        return self._disable_rich_output

    @disable_rich_output.setter
    def disable_rich_output(self, val: bool):
        """Set the flag to disable rich progress bar output."""
        self._disable_rich_output = val

    def __init__(
        self,
        system_config: SeBSConfig,
        docker_client: docker.client, # Explicitly type docker_client
        experimental_manifest: bool = False,
    ):
        """
        Initialize the DockerContainer manager.

        :param system_config: SeBS system configuration.
        :param docker_client: Docker client instance.
        :param experimental_manifest: Flag to use experimental Docker manifest features (default: False).
        """
        super().__init__()

        self.docker_client = docker_client
        self.experimental_manifest = experimental_manifest
        self.system_config = system_config
        self._disable_rich_output = False

    def find_image(self, repository_name: str, image_tag: str) -> bool:
        """
        Check if a Docker image exists in the registry.

        Can use experimental `docker manifest inspect` or fall back to `docker pull`
        if experimental features are not enabled or supported.

        :param repository_name: Name of the Docker repository.
        :param image_tag: Tag of the Docker image.
        :return: True if the image is found, False otherwise.
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

    def show_progress(self, txt: str, progress: Progress, layer_tasks: dict):
        """
        Parse Docker push progress messages and update a `rich.progress` display.

        Handles messages for layer pushing status, completion, and errors.

        :param txt: JSON string or dictionary containing Docker progress line.
        :param progress: `rich.progress.Progress` instance to update.
        :param layer_tasks: Dictionary to store progress task IDs for each layer.
        :raises Exception: If an error is reported in the progress line.
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

    def push_image(self, repository_uri: str, image_tag: str):
        """
        Push a Docker image to the specified repository and tag.

        Displays a progress bar using `rich.progress` unless `disable_rich_output` is True.

        :param repository_uri: URI of the Docker repository.
        :param image_tag: Tag of the image to push.
        :raises RuntimeError: If Docker API reports an error during push.
        :raises Exception: If any other Docker API error occurs.
        """
        try:
            if not self.disable_rich_output:
                layer_tasks = {}
                with Progress() as progress_display: # Renamed to avoid conflict
                    self.logging.info(f"Pushing image {image_tag} to {repository_uri}")
                    ret_stream = self.docker_client.images.push(
                        repository=repository_uri, tag=image_tag, stream=True, decode=True
                    )
                    for line in ret_stream:
                        self.show_progress(line, progress_display, layer_tasks)
            else:
                self.logging.info(f"Pushing image {image_tag} to {repository_uri}")
                ret_stream = self.docker_client.images.push(
                    repository=repository_uri, tag=image_tag, stream=True, decode=True
                )
                for val in ret_stream:
                    if "error" in val:
                        self.logging.error(f"Failed to push the image to registry {repository_uri}")
                        raise RuntimeError(val["error"]) # Raise the error message

        except docker.errors.APIError as e:
            self.logging.error(
                f"Failed to push the image to registry {repository_uri}. Error: {str(e)}"
            )
            raise e # Re-raise the original Docker APIError

    @abstractmethod
    def registry_name(
        self, benchmark: str, language_name: str, language_version: str, architecture: str
    ) -> Tuple[str, str, str, str]:
        """
        Generate provider-specific registry and image names.

        This method must be implemented by subclasses for specific FaaS providers.

        :param benchmark: Name of the benchmark.
        :param language_name: Name of the programming language.
        :param language_version: Version of the programming language.
        :param architecture: CPU architecture of the image.
        :return: Tuple containing:
            - registry_name (e.g., docker.io/user or provider-specific registry)
            - repository_name (e.g., benchmark-name or provider-specific repo name)
            - image_tag (e.g., language-version-architecture)
            - image_uri (fully qualified image URI)
        """
        pass

    def build_base_image(
        self,
        directory: str,
        language_name: str,
        language_version: str,
        architecture: str,
        benchmark: str,
        is_cached: bool,
    ) -> Tuple[bool, str]:
        """
        Build and push a base Docker image for a benchmark function.

        Workflow:
        1. If `is_cached` is True (meaning this is not the first build for this exact code
           and configuration according to SeBS's benchmark cache) and the image already
           exists in the registry, skip building and return the existing image URI.
        2. If `is_cached` is True but the image is NOT in the registry (e.g., manually deleted
           from registry), proceed to build and push.
        3. If `is_cached` is False (first time building this specific version), proceed to
           build and push.
        4. Subsequent builds (e.g., user modifies code, `is_cached` would be False for the
           new hash) will always rebuild and push.

        The Dockerfile used is expected to be named 'Dockerfile.function' and located in
        `DOCKER_DIR/{self.name()}/{language_name}/`.

        :param directory: Base directory of the benchmark code. A 'build' subdirectory
                          will be created here.
        :param language_name: Name of the programming language.
        :param language_version: Version of the programming language.
        :param architecture: Target CPU architecture for the image.
        :param benchmark: Name of the benchmark.
        :param is_cached: Boolean indicating if this benchmark version is already cached by SeBS.
        :return: Tuple (image_built_and_pushed: bool, image_uri: str).
                 The boolean is True if a new image was built and pushed, False if an
                 existing image from the registry was used.
        """
        registry_name, repository_name, image_tag, image_uri = self.registry_name(
            benchmark, language_name, language_version, architecture
        )

        # cached package, rebuild not enforced -> check for new one
        # if cached is true, no need to build and push the image.
        if is_cached:
            if self.find_image(repository_name, image_tag):
                self.logging.info(
                    f"Skipping building Docker image for {benchmark}, using "
                    f"Docker image {image_uri} from registry: {registry_name}."
                )
                return False, image_uri
            else:
                # image doesn't exist, let's continue
                self.logging.info(
                    f"Image {image_uri} doesn't exist in the registry, "
                    f"building the image for {benchmark}."
                )

        build_dir = os.path.join(directory, "build")
        os.makedirs(build_dir, exist_ok=True)

        shutil.copy(
            os.path.join(DOCKER_DIR, self.name(), language_name, "Dockerfile.function"),
            os.path.join(build_dir, "Dockerfile"),
        )
        for fn in os.listdir(directory):
            if fn not in ("index.js", "__main__.py"):
                file = os.path.join(directory, fn)
                shutil.move(file, build_dir)

        with open(os.path.join(build_dir, ".dockerignore"), "w") as f:
            f.write("Dockerfile")

        builder_image = self.system_config.benchmark_base_images(
            self.name(), language_name, architecture
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
            "BASE_IMAGE": builder_image,
            "TARGET_ARCHITECTURE": architecture,
        }
        image, _ = self.docker_client.images.build(
            tag=image_uri, path=build_dir, buildargs=buildargs
        )

        self.logging.info(
            f"Push the benchmark base image {repository_name}:{image_tag} "
            f"to registry: {registry_name}."
        )

        self.push_image(image_uri, image_tag)

        return True, image_uri
