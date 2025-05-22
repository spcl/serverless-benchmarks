from __future__ import annotations

from typing import cast, Optional
from dataclasses import dataclass

from sebs.benchmark import Benchmark
from sebs.faas.function import Function, FunctionConfig, Runtime
from sebs.storage.config import MinioConfig, ScyllaDBConfig


@dataclass
class OpenWhiskFunctionConfig(FunctionConfig):
    """
    Configuration specific to an OpenWhisk function.

    Extends the base FunctionConfig with OpenWhisk-specific attributes such as
    Docker image name, namespace, and configurations for object and NoSQL storage
    if they are self-hosted (e.g., Minio, ScyllaDB).

    Attributes:
        docker_image: Name of the Docker image for the function.
        namespace: OpenWhisk namespace (default is "_", the anonymous namespace).
        object_storage: Optional MinioConfig if self-hosted Minio is used.
        nosql_storage: Optional ScyllaDBConfig if self-hosted ScyllaDB is used.
    """
    # FIXME: merge docker_image with higher level abstraction for images in FunctionConfig
    docker_image: str = ""
    namespace: str = "_" # Default OpenWhisk namespace
    object_storage: Optional[MinioConfig] = None
    nosql_storage: Optional[ScyllaDBConfig] = None

    @staticmethod
    def deserialize(data: dict) -> OpenWhiskFunctionConfig:
        """
        Deserialize an OpenWhiskFunctionConfig object from a dictionary.

        Handles deserialization of nested Runtime, MinioConfig, and ScyllaDBConfig objects.

        :param data: Dictionary containing OpenWhiskFunctionConfig data.
        :return: An OpenWhiskFunctionConfig instance.
        """
        # Filter for known fields to avoid errors with extra keys in data
        known_keys = {field.name for field in OpenWhiskFunctionConfig.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in known_keys}

        filtered_data["runtime"] = Runtime.deserialize(filtered_data["runtime"])
        if "object_storage" in filtered_data and filtered_data["object_storage"] is not None:
            filtered_data["object_storage"] = MinioConfig.deserialize(filtered_data["object_storage"])
        if "nosql_storage" in filtered_data and filtered_data["nosql_storage"] is not None:
            filtered_data["nosql_storage"] = ScyllaDBConfig.deserialize(filtered_data["nosql_storage"])
        
        return OpenWhiskFunctionConfig(**filtered_data)

    def serialize(self) -> dict:
        """
        Serialize the OpenWhiskFunctionConfig to a dictionary.

        Serializes nested MinioConfig and ScyllaDBConfig if they exist.

        :return: A dictionary representation of the OpenWhiskFunctionConfig.
        """
        serialized_data = self.__dict__.copy()
        if self.object_storage:
            serialized_data["object_storage"] = self.object_storage.serialize()
        if self.nosql_storage:
            serialized_data["nosql_storage"] = self.nosql_storage.serialize()
        # Runtime and Architecture are handled by FunctionConfig.serialize via super().serialize() in Function
        return serialized_data

    @staticmethod
    def from_benchmark(benchmark: Benchmark) -> OpenWhiskFunctionConfig:
        """
        Create an OpenWhiskFunctionConfig instance from a Benchmark object.

        Uses the base class's `_from_benchmark` helper and casts to OpenWhiskFunctionConfig.
        Docker image and namespace are typically set after this initial creation.

        :param benchmark: The Benchmark instance.
        :return: An OpenWhiskFunctionConfig instance.
        """
        # Call the base class's _from_benchmark using super() correctly
        base_cfg = FunctionConfig._from_benchmark(benchmark, OpenWhiskFunctionConfig)
        # Ensure all fields of OpenWhiskFunctionConfig are initialized,
        # docker_image, namespace, object_storage, nosql_storage will have defaults from dataclass.
        # Specific values for these would be set by the OpenWhisk deployment logic.
        return base_cfg


class OpenWhiskFunction(Function):
    """
    Represents an OpenWhisk function (action).

    Extends the base Function class, using OpenWhiskFunctionConfig for its configuration.
    """
    def __init__(
        self, name: str, benchmark: str, code_package_hash: str, cfg: OpenWhiskFunctionConfig
    ):
        """
        Initialize an OpenWhiskFunction instance.

        :param name: Name of the OpenWhisk action.
        :param benchmark: Name of the benchmark this function belongs to.
        :param code_package_hash: Hash of the deployed code package.
        :param cfg: OpenWhiskFunctionConfig object.
        """
        super().__init__(benchmark, name, code_package_hash, cfg)

    @property
    def config(self) -> OpenWhiskFunctionConfig:
        """The OpenWhisk-specific configuration for this function."""
        return cast(OpenWhiskFunctionConfig, self._cfg)

    @staticmethod
    def typename() -> str:
        """Return the type name of this function implementation."""
        return "OpenWhisk.Function"

    def serialize(self) -> dict:
        """
        Serialize the OpenWhiskFunction instance to a dictionary.

        Ensures that the OpenWhisk-specific configuration is also serialized.

        :return: Dictionary representation of the OpenWhiskFunction.
        """
        # super().serialize() already includes self.config.serialize()
        # No, Function.serialize() calls self.config.serialize().
        # If OpenWhiskFunctionConfig.serialize() is correctly implemented, this is fine.
        return super().serialize()

    @staticmethod
    def deserialize(cached_config: dict) -> OpenWhiskFunction:
        """
        Deserialize an OpenWhiskFunction instance from a dictionary.

        Typically used when loading function details from a cache.

        :param cached_config: Dictionary containing serialized OpenWhiskFunction data.
        :return: A new OpenWhiskFunction instance.
        """
        from sebs.faas.function import Trigger # Already imported at top-level
        from sebs.openwhisk.triggers import LibraryTrigger, HTTPTrigger # Specific to OpenWhisk triggers

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
