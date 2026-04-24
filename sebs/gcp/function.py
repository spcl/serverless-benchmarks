# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
"""Google Cloud Platform function implementation for SeBS.

This module provides the GCPFunction class that represents a Cloud Function
deployed on Google Cloud Platform. It handles function metadata, serialization,
deserialization, and bucket management for code deployment.

Classes:
    GCPFunction: Represents a deployed Google Cloud Function with GCP-specific features

Example:
    Creating a GCP function instance:

        config = FunctionConfig(memory=256, timeout=60, runtime="python39")
        function = GCPFunction("my-function", "benchmark-name", "hash123", config)
"""
from __future__ import annotations

from enum import Enum
from typing import cast, Dict, Optional, Union

from sebs.faas.config import Resources
from sebs.faas.function import Function, FunctionConfig
from sebs.gcp.storage import GCPStorage

from sebs.gcp.config import GCPFunctionGen1Config, GCPFunctionGen2Config, GCPContainerConfig


class FunctionDeploymentType(str, Enum):
    """Enumeration of deployment methods on GCP.

    - FUNCTION_GEN1: Original Google Cloud Functions.
    - FUNCTION_GEN2: Google Cloud Functions gen2, based on Cloud Run.
    - CONTAINER: Google Cloud Run containers.
    """

    FUNCTION_GEN1 = "function-gen1"
    FUNCTION_GEN2 = "function-gen2"
    CONTAINER = "container"

    @property
    def is_container(self) -> bool:
        return self == FunctionDeploymentType.CONTAINER

    @staticmethod
    def deserialize(val: str) -> FunctionDeploymentType:
        """Deserialize a string value to a FunctionDeploymentEngine enum.

        Args:
            val: String value to convert to enum

        Returns:
            FunctionDeploymentEngine: Corresponding enum value

        Raises:
            Exception: If the value doesn't match any enum member
        """
        for member in FunctionDeploymentType:
            if member.value == val:
                return member
        raise Exception(f"Unknown GCP function deployment type {val}")


class GCPFunction(Function):
    """Represents a Google Cloud Function with GCP-specific functionality.

    Extends the base Function class with GCP-specific features like bucket
    management for code storage and GCP-specific serialization/deserialization.

    Attributes:
        bucket: Cloud Storage bucket name containing the function's code
    """

    def __init__(
        self,
        name: str,
        benchmark: str,
        code_package_hash: str,
        cfg: FunctionConfig,
        deployment_type: FunctionDeploymentType,
        deployment_config: Union[GCPFunctionGen1Config, GCPFunctionGen2Config, GCPContainerConfig],
        bucket: Optional[str] = None,
        container_uri: Optional[str] = None,
    ) -> None:
        """Initialize a GCP Cloud Function instance.

        Args:
            name: Function name on GCP
            benchmark: Name of the benchmark this function implements
            code_package_hash: Hash of the code package for version tracking
            cfg: Function configuration (memory, timeout, etc.)
            deployment_type: Type of deployment (function-gen1, container-gen1, etc.)
            bucket: Optional Cloud Storage bucket name for code storage
            deployment_config: Deployment-specific configuration
        """
        super().__init__(benchmark, name, code_package_hash, cfg)
        self.bucket = bucket
        self._container_uri = container_uri
        self._deployment_type = deployment_type
        self._deployment_config = deployment_config

    @staticmethod
    def typename() -> str:
        """Get the type name for this function implementation.

        Returns:
            Type name string for GCP functions
        """
        return "GCP.GCPFunction"

    @property
    def deployment_type(self) -> FunctionDeploymentType:
        return self._deployment_type

    @property
    def deployment_config(
        self,
    ) -> Union[GCPFunctionGen1Config, GCPFunctionGen2Config, GCPContainerConfig]:
        return self._deployment_config

    def serialize(self) -> Dict:
        """Serialize function to dictionary for cache storage.
        Adds code bucket in cloud storage.

        Returns:
            Dictionary containing function state including bucket information
        """
        out = {
            **super().serialize(),
            "container-uri": self._container_uri,
            "bucket": self.bucket,
            "deployment_type": self.deployment_type,
            "deployment_config": self._deployment_config.serialize(),
        }
        return out

    @staticmethod
    def deserialize(cached_config: Dict) -> "GCPFunction":
        """Deserialize function from cached configuration.

        Reconstructs a GCPFunction instance from cached data including
        triggers and configuration. Handles both Library and HTTP triggers.

        Args:
            cached_config: Dictionary containing cached function configuration

        Returns:
            Reconstructed GCPFunction instance with triggers

        Raises:
            AssertionError: If an unknown trigger type is encountered
        """
        from sebs.faas.function import Trigger
        from sebs.gcp.triggers import LibraryTrigger, HTTPTrigger
        from sebs.gcp.config import (
            GCPFunctionGen1Config,
            GCPFunctionGen2Config,
            GCPContainerConfig,
        )

        cfg = FunctionConfig.deserialize(cached_config["config"])
        deployment_type = FunctionDeploymentType.deserialize(cached_config["deployment_type"])

        dep_cfg_dict = cached_config["deployment_config"]
        deployment_config: Union[GCPFunctionGen1Config, GCPFunctionGen2Config, GCPContainerConfig]
        if deployment_type == FunctionDeploymentType.FUNCTION_GEN1:
            deployment_config = GCPFunctionGen1Config.deserialize(dep_cfg_dict)
        elif deployment_type == FunctionDeploymentType.FUNCTION_GEN2:
            deployment_config = GCPFunctionGen2Config.deserialize(dep_cfg_dict)
        else:
            deployment_config = GCPContainerConfig.deserialize(dep_cfg_dict)

        ret = GCPFunction(
            cached_config["name"],
            cached_config["benchmark"],
            cached_config["hash"],
            cfg,
            deployment_type,
            deployment_config,
            cached_config["bucket"],
            cached_config["container-uri"],
        )
        for trigger in cached_config["triggers"]:
            trigger_type = cast(
                Trigger,
                {"Library": LibraryTrigger, "HTTP": HTTPTrigger}.get(trigger["type"]),
            )
            assert trigger_type, "Unknown trigger type {}".format(trigger["type"])
            ret.add_trigger(trigger_type.deserialize(trigger))
        return ret

    def container_uri(self) -> str | None:
        return self._container_uri

    def code_bucket(self, benchmark: str, storage_client: GCPStorage) -> str:
        """Get or create the Cloud Storage bucket for function code.

        Returns the bucket name where the function's code is stored,
        creating a deployment bucket if none is assigned.

        Args:
            benchmark: Benchmark name (unused but kept for compatibility)
            storage_client: GCP storage client for bucket operations

        Returns:
            Cloud Storage bucket name containing function code
        """
        if not self.bucket:
            self.bucket = storage_client.get_bucket(Resources.StorageBucketType.DEPLOYMENT)
        return self.bucket
