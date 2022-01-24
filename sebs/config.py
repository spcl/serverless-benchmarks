import json
from typing import Dict, List, Optional

from sebs.utils import project_absolute_path


class SeBSConfig:
    def __init__(self):
        with open(project_absolute_path("config", "systems.json"), "r") as cfg:
            self._system_config = json.load(cfg)

    def docker_repository(self) -> str:
        return self._system_config["general"]["docker_repository"]

    def deployment_packages(self, deployment_name: str, language_name: str) -> Dict[str, str]:
        return self._system_config[deployment_name]["languages"][language_name]["deployment"][
            "packages"
        ]

    def deployment_files(self, deployment_name: str, language_name: str) -> List[str]:
        return self._system_config[deployment_name]["languages"][language_name]["deployment"][
            "files"
        ]

    def docker_image_types(self, deployment_name: str, language_name: str) -> List[str]:
        return self._system_config[deployment_name]["languages"][language_name]["images"]

    def supported_language_versions(self, deployment_name: str, language_name: str) -> List[str]:
        return self._system_config[deployment_name]["languages"][language_name][
            "base_images"
        ].keys()

    def benchmark_base_images(self, deployment_name: str, language_name: str) -> Dict[str, str]:
        return self._system_config[deployment_name]["languages"][language_name]["base_images"]

    def benchmark_image_name(
        self,
        system: str,
        benchmark: str,
        language_name: str,
        language_version: str,
        registry: Optional[str] = None,
    ) -> str:

        tag = self.benchmark_image_tag(system, benchmark, language_name, language_version)
        repo_name = self.docker_repository()
        if registry is not None:
            return f"{registry}/{repo_name}:{tag}"
        else:
            return f"{repo_name}:{tag}"

    def benchmark_image_tag(
        self, system: str, benchmark: str, language_name: str, language_version: str
    ) -> str:
        return f"function.{system}.{benchmark}.{language_name}-{language_version}"

    def username(self, deployment_name: str, language_name: str) -> str:
        return self._system_config[deployment_name]["languages"][language_name]["username"]
