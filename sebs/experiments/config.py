# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
"""Configuration management for benchmark experiments.

This module provides the configuration class for benchmark experiments,
handling settings such as:
- Runtime environment (language, version)
- Architecture (x64, arm64)
- Deployment type (container, package)
- Code and storage update flags
- Experiment-specific settings

The Config class handles serialization and deserialization of experiment
configurations, allowing them to be loaded from and saved to configuration files.
"""

from typing import Dict

from sebs.faas.function import Runtime


class SystemVariant:
    """Deployment variant selected for an experiment.

    The variant is provider-specific, but exposes a shared ``is_container``
    property for logic that only cares about the package vs container split.
    """

    def __init__(self, value: str):
        """Initialize the system variant.

        Args:
            value: Provider-specific deployment variant name.
        """
        self._value = value

    @property
    def value(self) -> str:
        """Get the provider-specific deployment variant name."""
        return self._value

    @property
    def is_container(self) -> bool:
        """Return whether this deployment variant uses containers."""
        return self._value == "container"

    def serialize(self) -> str:
        """Serialize the deployment variant to a string."""
        return self._value

    @staticmethod
    def deserialize(value: str | "SystemVariant") -> "SystemVariant":
        """Deserialize a deployment variant from a string or passthrough object."""
        if isinstance(value, SystemVariant):
            return value
        return SystemVariant(value)

    def __eq__(self, other: object) -> bool:
        """Compare two system variants."""
        if not isinstance(other, SystemVariant):
            return False
        return self.value == other.value


class Config:
    """Configuration class for benchmark experiments.

    This class manages the configuration settings for benchmark experiments,
    including runtime environment, architecture, deployment type, and
    experiment-specific settings.

    Attributes:
        _update_code: Whether to update function code
        _update_storage: Whether to update storage resources
        _system_variant: Deployment variant selected for the target provider
        _download_results: Whether to download experiment results
        _architecture: CPU architecture (e.g., "x64", "arm64")
        _flags: Dictionary of boolean flags for custom settings
        _experiment_configs: Dictionary of experiment-specific settings
        _runtime: Runtime environment (language and version)
    """

    def __init__(self):
        """Initialize a new experiment configuration with default values."""
        self._update_code: bool = False
        self._update_storage: bool = False
        self._system_variant = SystemVariant("package")
        self._download_results: bool = False
        self._architecture: str = "x64"
        self._flags: Dict[str, bool] = {}
        self._experiment_configs: Dict[str, dict] = {}
        self._runtime = Runtime(None, None)

    @property
    def update_code(self) -> bool:
        """Get whether to update function code.

        Returns:
            True if function code should be updated, False otherwise
        """
        return self._update_code

    @update_code.setter
    def update_code(self, val: bool):
        """Set whether to update function code.

        Args:
            val: True if function code should be updated, False otherwise
        """
        self._update_code = val

    @property
    def update_storage(self) -> bool:
        """Get whether to update storage resources.

        Returns:
            True if storage resources should be updated, False otherwise
        """
        return self._update_storage

    def check_flag(self, key: str) -> bool:
        """Check if a specific experiment flag is set.

        Currently it is only used to let benchmark know that Docker
        volumes are disabled (e.g., in CircleCI environment).

        Args:
            key: Name of the flag to check

        Returns:
            Value of the flag, or False if the flag is not set
        """
        return False if key not in self._flags else self._flags[key]

    @property
    def runtime(self) -> Runtime:
        """Get the runtime environment.

        Returns:
            Runtime environment (language and version)
        """
        return self._runtime

    @property
    def architecture(self) -> str:
        """Get the CPU architecture.

        Returns:
            CPU architecture (e.g., "x64", "arm64")
        """
        return self._architecture

    @property
    def system_variant(self) -> SystemVariant:
        """Get the selected deployment variant."""
        return self._system_variant

    def experiment_settings(self, name: str) -> dict:
        """Get settings for a specific experiment.

        Args:
            name: Name of the experiment

        Returns:
            Dictionary of experiment-specific settings

        Raises:
            KeyError: If the experiment name is not found in the configuration
        """
        return self._experiment_configs[name]

    def serialize(self) -> dict:
        """Serialize the configuration to a dictionary.

        This method converts the configuration object to a dictionary
        that can be saved to a file or passed to other components.

        Returns:
            Dictionary representation of the configuration
        """
        out = {
            "update_code": self._update_code,
            "update_storage": self._update_storage,
            "download_results": self._download_results,
            "runtime": self._runtime.serialize(),
            "flags": self._flags,
            "experiments": self._experiment_configs,
            "architecture": self._architecture,
            "system_variant": self._system_variant.serialize(),
        }
        return out

    # FIXME: 3.7+ python with future annotations
    @staticmethod
    def deserialize(config: dict) -> "Config":
        """Deserialize a configuration from a dictionary.

        This method creates a new configuration object from a dictionary
        representation, which may have been loaded from a file or passed
        from another component.

        Args:
            config: Dictionary representation of the configuration

        Returns:
            A new configuration object with settings from the dictionary

        Note:
            This method requires Python 3.7+ for proper type annotations.
            The string type annotation is a forward reference to the Config class.
        """
        cfg = Config()
        cfg._update_code = config["update_code"]
        cfg._update_storage = config["update_storage"]
        cfg._download_results = config["download_results"]
        if "system_variant" in config:
            cfg._system_variant = SystemVariant.deserialize(config["system_variant"])
        else:
            legacy_is_container = config.get("container_deployment", False)
            cfg._system_variant = SystemVariant("container" if legacy_is_container else "package")
        cfg._runtime = Runtime.deserialize(config["runtime"])
        cfg._flags = config["flags"] if "flags" in config else {}
        cfg._architecture = config["architecture"]

        # Import experiment types here to avoid circular import
        from sebs.experiments import (
            NetworkPingPong,
            PerfCost,
            InvocationOverhead,
            EvictionModel,
        )

        # Load experiment-specific settings if present
        for exp in [NetworkPingPong, PerfCost, InvocationOverhead, EvictionModel]:
            if exp.name() in config:
                cfg._experiment_configs[exp.name()] = config[exp.name()]

        return cfg
