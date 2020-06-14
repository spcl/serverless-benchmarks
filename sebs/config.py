import json
from typing import Dict, List

from sebs.utils import project_absolute_path


class SeBSConfig:
    def __init__(self):
        self._system_config = json.load(
            open(project_absolute_path("config", "systems.json"), "r")
        )

    def deployment_packages(
        self, deployment_name: str, language_name: str
    ) -> Dict[str, str]:
        return self._system_config[deployment_name]["languages"][language_name][
            "deployment"
        ]["packages"]

    def deployment_files(self, deployment_name: str, language_name: str) -> List[str]:
        return self._system_config[deployment_name]["languages"][language_name][
            "deployment"
        ]["files"]

    def docker_image_types(self, deployment_name: str, language_name: str) -> List[str]:
        return self._system_config[deployment_name]["languages"][language_name][
            "images"
        ]

    def supported_language_versions(
        self, deployment_name: str, language_name: str
    ) -> List[str]:
        return self._system_config[deployment_name]["languages"][language_name][
            "base_images"
        ].keys()
