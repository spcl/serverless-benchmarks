from typing import Dict

from sebs.faas.function import Runtime


class Config:
    """
    Configuration class for SeBS experiments.

    Manages settings related to code and storage updates, container deployment,
    result downloading, runtime, architecture, and experiment-specific flags
    and configurations.
    """
    def __init__(self):
        """Initialize a new experiment configuration with default values."""
        self._update_code: bool = False
        self._update_storage: bool = False
        self._container_deployment: bool = False
        self._download_results: bool = False
        self._architecture: str = "x64"
        self._flags: Dict[str, bool] = {}
        self._experiment_configs: Dict[str, dict] = {}
        self._runtime = Runtime(None, None)

    @property
    def update_code(self) -> bool:
        """Flag indicating whether to update function code packages."""
        return self._update_code

    @update_code.setter
    def update_code(self, val: bool):
        """Set the flag for updating function code packages."""
        self._update_code = val

    @property
    def update_storage(self) -> bool:
        """Flag indicating whether to update input/output storage resources."""
        return self._update_storage

    def check_flag(self, key: str) -> bool:
        """
        Check if a specific experiment flag is set.

        :param key: The name of the flag.
        :return: True if the flag is set and True, False otherwise.
        """
        return False if key not in self._flags else self._flags[key]

    @property
    def runtime(self) -> Runtime:
        """The target runtime for the experiment (language and version)."""
        return self._runtime

    @property
    def architecture(self) -> str:
        """The target CPU architecture for the experiment (e.g., 'x64', 'arm64')."""
        return self._architecture

    @property
    def container_deployment(self) -> bool:
        """Flag indicating whether to deploy functions as container images."""
        return self._container_deployment

    def experiment_settings(self, name: str) -> dict:
        """
        Get the specific configuration settings for a named experiment.

        :param name: The name of the experiment.
        :return: A dictionary containing the experiment's settings.
        """
        return self._experiment_configs[name]

    def serialize(self) -> dict:
        """
        Serialize the experiment configuration to a dictionary.

        :return: A dictionary representation of the Config object.
        """
        out = {
            "update_code": self._update_code,
            "update_storage": self._update_storage,
            "download_results": self._download_results,
            "runtime": self._runtime.serialize(),
            "flags": self._flags,
            "experiments": self._experiment_configs,
            "architecture": self._architecture,
            "container_deployment": self._container_deployment,
        }
        return out

    # FIXME: 3.7+ python with future annotations
    @staticmethod
    def deserialize(config: dict) -> "Config":
        """
        Deserialize a Config object from a dictionary.

        Populates the Config instance with values from the dictionary,
        including experiment-specific configurations.

        :param config: A dictionary containing serialized Config data.
        :return: A new Config instance.
        """
        cfg = Config()
        cfg._update_code = config["update_code"]
        cfg._update_storage = config["update_storage"]
        cfg._download_results = config["download_results"]
        cfg._container_deployment = config["container_deployment"]
        cfg._runtime = Runtime.deserialize(config["runtime"])
        cfg._flags = config["flags"] if "flags" in config else {}
        cfg._architecture = config["architecture"]

        from sebs.experiments import (
            NetworkPingPong,
            PerfCost,
            InvocationOverhead,
            EvictionModel,
        )

        for exp in [NetworkPingPong, PerfCost, InvocationOverhead, EvictionModel]:
            if exp.name() in config:
                cfg._experiment_configs[exp.name()] = config[exp.name()]

        return cfg
