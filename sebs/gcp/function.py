from typing import cast, Optional

from sebs.faas.config import Resources
from sebs.faas.function import Function, FunctionConfig
from sebs.gcp.storage import GCPStorage


class GCPFunction(Function):
    """
    Represents a Google Cloud Function.

    Extends the base Function class with GCP-specific attributes like the
    Cloud Storage bucket used for code deployment.
    """
    def __init__(
        self,
        name: str,
        benchmark: str,
        code_package_hash: str,
        cfg: FunctionConfig,
        bucket: Optional[str] = None,
    ):
        """
        Initialize a GCPFunction instance.

        :param name: Name of the Google Cloud Function.
        :param benchmark: Name of the benchmark this function belongs to.
        :param code_package_hash: Hash of the deployed code package.
        :param cfg: FunctionConfig object with memory, timeout, etc.
        :param bucket: Optional Cloud Storage bucket name where the code package is stored.
        """
        super().__init__(benchmark, name, code_package_hash, cfg)
        self.bucket = bucket

    @staticmethod
    def typename() -> str:
        """Return the type name of this function implementation."""
        return "GCP.GCPFunction"

    def serialize(self) -> dict:
        """
        Serialize the GCPFunction instance to a dictionary.

        Includes GCP-specific attributes (bucket) along with base Function attributes.

        :return: Dictionary representation of the GCPFunction.
        """
        return {
            **super().serialize(),
            "bucket": self.bucket,
        }

    @staticmethod
    def deserialize(cached_config: dict) -> "GCPFunction":
        """
        Deserialize a GCPFunction instance from a dictionary.

        Typically used when loading function details from a cache.

        :param cached_config: Dictionary containing serialized GCPFunction data.
        :return: A new GCPFunction instance.
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

    def code_bucket(self, benchmark: str, storage_client: GCPStorage) -> Optional[str]:
        """
        Get or assign the Google Cloud Storage bucket for code deployment.

        If a bucket is not already assigned to this function, it retrieves
        the deployment bucket from the GCPStorage client.

        :param benchmark: Name of the benchmark (used by storage_client if creating a new bucket).
        :param storage_client: GCPStorage client instance.
        :return: The name of the Cloud Storage bucket used for code deployment, or None if not set.
        """
        if not self.bucket:
            self.bucket = storage_client.get_bucket(Resources.StorageBucketType.DEPLOYMENT)
        return self.bucket
