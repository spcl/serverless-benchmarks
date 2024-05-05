from typing import cast, Optional

from sebs.faas.config import Resources
from sebs.faas.function import Function, FunctionConfig
from sebs.gcp.storage import GCPStorage


class GCPFunction(Function):
    def __init__(
        self,
        name: str,
        benchmark: str,
        code_package_hash: str,
        cfg: FunctionConfig,
        bucket: Optional[str] = None,
    ):
        super().__init__(benchmark, name, code_package_hash, cfg)
        self.bucket = bucket

    @staticmethod
    def typename() -> str:
        return "GCP.GCPFunction"

    def serialize(self) -> dict:
        return {
            **super().serialize(),
            "bucket": self.bucket,
        }

    @staticmethod
    def deserialize(cached_config: dict) -> "GCPFunction":
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

    def code_bucket(self, benchmark: str, storage_client: GCPStorage):
        if not self.bucket:
            self.bucket = storage_client.get_bucket(Resources.StorageBucketType.DEPLOYMENT)
        return self.bucket
