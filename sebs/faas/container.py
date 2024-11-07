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
    @staticmethod
    @abstractmethod
    def name() -> str:
        pass

    @property
    def disable_rich_output(self) -> bool:
        return self._disable_rich_output

    @disable_rich_output.setter
    def disable_rich_output(self, val: bool):
        self._disable_rich_output = val

    def __init__(
        self,
        system_config: SeBSConfig,
        docker_client,
        experimental_manifest: bool = False,
    ):
        super().__init__()

        self.docker_client = docker_client
        self.experimental_manifest = experimental_manifest
        self.system_config = system_config
        self._disable_rich_output = False

    def find_image(self, repository_name, image_tag) -> bool:

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

    def push_image(self, repository_uri, image_tag):
        try:

            if not self.disable_rich_output:

                layer_tasks = {}
                with Progress() as progress:

                    self.logging.info(f"Pushing image {image_tag} to {repository_uri}")
                    ret = self.docker_client.images.push(
                        repository=repository_uri, tag=image_tag, stream=True, decode=True
                    )
                    for line in ret:
                        self.show_progress(line, progress, layer_tasks)

            else:
                self.logging.info(f"Pushing image {image_tag} to {repository_uri}")
                ret = self.docker_client.images.push(
                    repository=repository_uri, tag=image_tag, stream=True, decode=True
                )

                for val in ret:
                    if "error" in val:
                        self.logging.error(f"Failed to push the image to registry {repository_uri}")
                        raise RuntimeError(val)

        except docker.errors.APIError as e:
            self.logging.error(
                f"Failed to push the image to registry {repository_uri}. Error: {str(e)}"
            )
            raise e

    @abstractmethod
    def registry_name(
        self, benchmark: str, language_name: str, language_version: str, architecture: str
    ) -> Tuple[str, str, str, str]:
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
        When building function for the first time (according to SeBS cache),
        check if Docker image is available in the registry.
        If yes, then skip building.
        If no, then continue building.

        For every subsequent build, we rebuild image and push it to the
        registry. These are triggered by users modifying code and enforcing
        a build.
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

        buildargs = {"VERSION": language_version, "BASE_IMAGE": builder_image}
        image, _ = self.docker_client.images.build(
            tag=image_uri, path=build_dir, buildargs=buildargs
        )

        self.logging.info(
            f"Push the benchmark base image {repository_name}:{image_tag} "
            f"to registry: {registry_name}."
        )

        self.push_image(image_uri, image_tag)

        return True, image_uri
