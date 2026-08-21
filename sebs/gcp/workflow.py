"""GCP Workflows deployment model for SeBS."""

from typing import List, cast, Optional

from sebs.faas.config import Resources
from sebs.faas.function import FunctionConfig, Workflow
from sebs.gcp.function import GCPFunction
from sebs.gcp.storage import GCPStorage


class GCPWorkflow(Workflow):
    """Workflow deployed as a GCP Workflows resource."""

    def __init__(
        self,
        name: str,
        functions: List[GCPFunction],
        benchmark: str,
        code_package_hash: str,
        cfg: FunctionConfig,
        bucket: Optional[str] = None,
    ):
        """Create a GCP workflow object."""
        super().__init__(benchmark, name, code_package_hash, cfg)
        self.functions = functions
        self.bucket = bucket

    @staticmethod
    def typename() -> str:
        """Get the serialized workflow type name."""
        return "GCP.GCPWorkflow"

    def serialize(self) -> dict:
        """Serialize the workflow and child Cloud Functions."""
        return {
            **super().serialize(),
            "functions": [f.serialize() for f in self.functions],
            "bucket": self.bucket,
        }

    @staticmethod
    def deserialize(cached_config: dict) -> "GCPWorkflow":
        """Deserialize a cached GCP workflow."""
        from sebs.faas.function import Trigger
        from sebs.gcp.triggers import WorkflowLibraryTrigger, HTTPTrigger

        cfg = FunctionConfig.deserialize(cached_config["config"])
        funcs = [GCPFunction.deserialize(f) for f in cached_config["functions"]]
        ret = GCPWorkflow(
            cached_config["name"],
            funcs,
            cached_config["benchmark"],
            cached_config["hash"],
            cfg,
            cached_config["bucket"],
        )
        for trigger in cached_config["triggers"]:
            trigger_type = cast(
                Trigger,
                {"Library": WorkflowLibraryTrigger, "HTTP": HTTPTrigger}.get(trigger["type"]),
            )
            assert trigger_type, "Unknown trigger type {}".format(trigger["type"])
            ret.add_trigger(trigger_type.deserialize(trigger))
        return ret

    def code_bucket(self, benchmark: str, storage_client: GCPStorage) -> str:
        """Get or create the deployment bucket for workflow child code."""
        if not self.bucket:
            self.bucket = storage_client.get_bucket(Resources.StorageBucketType.DEPLOYMENT)
        return self.bucket
