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

from typing import cast, Dict, Optional

from sebs.faas.config import Resources
from sebs.faas.function import Function, FunctionConfig
from sebs.gcp.storage import GCPStorage


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
        bucket: Optional[str] = None,
    ) -> None:
        """Initialize a GCP Cloud Function instance.
        
        Args:
            name: Function name on GCP
            benchmark: Name of the benchmark this function implements
            code_package_hash: Hash of the code package for version tracking
            cfg: Function configuration (memory, timeout, etc.)
            bucket: Optional Cloud Storage bucket name for code storage
        """
        super().__init__(benchmark, name, code_package_hash, cfg)
        self.bucket = bucket

    @staticmethod
    def typename() -> str:
        """Get the type name for this function implementation.
        
        Returns:
            Type name string for GCP functions
        """
        return "GCP.GCPFunction"

    def serialize(self) -> Dict:
        """Serialize function to dictionary for cache storage.
        
        Returns:
            Dictionary containing function state including bucket information
        """
        return {
            **super().serialize(),
            "bucket": self.bucket,
        }

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

        cfg = FunctionConfig.deserialize(cached_config["config"])
        ret = GCPFunction(
            cached_config["name"],
            cached_config["benchmark"],
            cached_config["hash"],
            cfg,
            cached_config["bucket"],
        )
        for trigger in cached_config["triggers"]:
            trigger_type = cast(
                Trigger,
                {"Library": LibraryTrigger, "HTTP": HTTPTrigger}.get(trigger["type"]),
            )
            assert trigger_type, "Unknown trigger type {}".format(trigger["type"])
            ret.add_trigger(trigger_type.deserialize(trigger))
        return ret

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
