"""OpenWhisk function and configuration classes for SeBS.

This module provides OpenWhisk-specific implementations of function configuration
and function management for the SeBS benchmarking framework. It handles function
configuration serialization, Docker image management, and storage integration.

Classes:
    OpenWhiskFunctionConfig: Configuration data class for OpenWhisk functions
    OpenWhiskFunction: OpenWhisk-specific function implementation
"""

from __future__ import annotations

from typing import cast, Optional, Dict, Any
from dataclasses import dataclass

from sebs.benchmark import Benchmark
from sebs.faas.function import Function, FunctionConfig, Runtime
from sebs.storage.config import MinioConfig, ScyllaDBConfig


@dataclass
class OpenWhiskFunctionConfig(FunctionConfig):
    """
    Configuration data class for OpenWhisk functions.
    
    This class extends the base FunctionConfig to include OpenWhisk-specific
    configuration parameters such as Docker image information, namespace settings,
    and storage configurations for both object and NoSQL storage.
    
    Attributes:
        docker_image: Docker image URI used for the function deployment
        namespace: OpenWhisk namespace (default: "_" for default namespace)
        object_storage: Minio object storage configuration if required
        nosql_storage: ScyllaDB NoSQL storage configuration if required
    
    Note:
        The docker_image attribute should be merged with higher-level
        image abstraction in future refactoring.
    """

    # FIXME: merge with higher level abstraction for images
    docker_image: str = ""
    namespace: str = "_"
    object_storage: Optional[MinioConfig] = None
    nosql_storage: Optional[ScyllaDBConfig] = None

    @staticmethod
    def deserialize(data: Dict[str, Any]) -> OpenWhiskFunctionConfig:
        """
        Deserialize configuration from dictionary data.
        
        Args:
            data: Dictionary containing serialized configuration data
        
        Returns:
            OpenWhiskFunctionConfig instance with deserialized data
        """
        keys = list(OpenWhiskFunctionConfig.__dataclass_fields__.keys())
        data = {k: v for k, v in data.items() if k in keys}
        data["runtime"] = Runtime.deserialize(data["runtime"])
        data["object_storage"] = MinioConfig.deserialize(data["object_storage"])
        data["nosql_storage"] = ScyllaDBConfig.deserialize(data["nosql_storage"])
        return OpenWhiskFunctionConfig(**data)

    def serialize(self) -> Dict[str, Any]:
        """
        Serialize configuration to dictionary format.
        
        Returns:
            Dictionary containing all configuration data
        """
        return self.__dict__

    @staticmethod
    def from_benchmark(benchmark: Benchmark) -> OpenWhiskFunctionConfig:
        """
        Create configuration from benchmark specification.
        
        Args:
            benchmark: Benchmark instance containing configuration requirements
        
        Returns:
            OpenWhiskFunctionConfig instance initialized from benchmark
        """
        return super(OpenWhiskFunctionConfig, OpenWhiskFunctionConfig)._from_benchmark(
            benchmark, OpenWhiskFunctionConfig
        )


class OpenWhiskFunction(Function):
    """
    OpenWhisk-specific function implementation for SeBS.
    
    This class provides OpenWhisk-specific function management including
    configuration handling, serialization, and trigger management. It integrates
    with OpenWhisk actions and maintains Docker image information.
    
    Attributes:
        _cfg: OpenWhisk-specific function configuration
    
    Example:
        >>> config = OpenWhiskFunctionConfig.from_benchmark(benchmark)
        >>> function = OpenWhiskFunction("test-func", "benchmark-name", "hash123", config)
    """
    
    def __init__(
        self, name: str, benchmark: str, code_package_hash: str, cfg: OpenWhiskFunctionConfig
    ) -> None:
        """
        Initialize OpenWhisk function.
        
        Args:
            name: Function name (OpenWhisk action name)
            benchmark: Name of the benchmark this function implements
            code_package_hash: Hash of the code package for cache validation
            cfg: OpenWhisk-specific function configuration
        """
        super().__init__(benchmark, name, code_package_hash, cfg)

    @property
    def config(self) -> OpenWhiskFunctionConfig:
        """
        Get OpenWhisk-specific function configuration.
        
        Returns:
            OpenWhiskFunctionConfig instance with current settings
        """
        return cast(OpenWhiskFunctionConfig, self._cfg)

    @staticmethod
    def typename() -> str:
        """
        Get the type name for this function class.
        
        Returns:
            String identifier for OpenWhisk functions
        """
        return "OpenWhisk.Function"

    def serialize(self) -> Dict[str, Any]:
        """
        Serialize function to dictionary format.
        
        Returns:
            Dictionary containing function data and OpenWhisk-specific configuration
        """
        return {**super().serialize(), "config": self._cfg.serialize()}

    @staticmethod
    def deserialize(cached_config: Dict[str, Any]) -> OpenWhiskFunction:
        """
        Deserialize function from cached configuration data.
        
        Args:
            cached_config: Dictionary containing cached function configuration
                          and trigger information
        
        Returns:
            OpenWhiskFunction instance with deserialized configuration and triggers
        
        Raises:
            AssertionError: If unknown trigger type is encountered
        """
        from sebs.faas.function import Trigger
        from sebs.openwhisk.triggers import LibraryTrigger, HTTPTrigger

        cfg = OpenWhiskFunctionConfig.deserialize(cached_config["config"])
        ret = OpenWhiskFunction(
            cached_config["name"], cached_config["benchmark"], cached_config["hash"], cfg
        )
        for trigger in cached_config["triggers"]:
            trigger_type = cast(
                Trigger,
                {"Library": LibraryTrigger, "HTTP": HTTPTrigger}.get(trigger["type"]),
            )
            assert trigger_type, "Unknown trigger type {}".format(trigger["type"])
            ret.add_trigger(trigger_type.deserialize(trigger))
        return ret
