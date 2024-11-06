import docker
import json

from rich.progress import Progress

from sebs.config import SeBSConfig
from sebs.utils import LoggingBase, execute


class DockerContainer(LoggingBase):
    def __init__(
        self, system_config: SeBSConfig, docker_client, experimental_manifest: bool = False
    ):
        super().__init__()

        self.docker_client = docker_client
        self.experimental_manifest = experimental_manifest
        self.system_config = system_config

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

            layer_tasks = {}
            with Progress() as progress:

                self.logging.info(f"Pushing image {image_tag} to {repository_uri}")
                ret = self.docker_client.images.push(
                    repository=repository_uri, tag=image_tag, stream=True, decode=True
                )
                for line in ret:
                    self.show_progress(line, progress, layer_tasks)

        except docker.errors.APIError as e:
            self.logging.error(
                f"Failed to push the image to registry {repository_uri}. Error: {str(e)}"
            )
            raise e
