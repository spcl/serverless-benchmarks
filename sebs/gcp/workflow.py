from typing import cast, Optional

from sebs.faas.workflow import Workflow
from sebs.gcp.storage import GCPStorage


class GCPWorkflow(Workflow):
    def __init__(
        self,
        name: str,
        benchmark: str,
        code_package_hash: str,
        timeout: int,
        memory: int,
        bucket: Optional[str] = None,
    ):
        super().__init__(benchmark, name, code_package_hash)
        self.timeout = timeout
        self.memory = memory
        self.bucket = bucket

    @staticmethod
    def typename() -> str:
        return "GCP.GCPWorkflow"

    def serialize(self) -> dict:
        return {
            **super().serialize(),
            "timeout": self.timeout,
            "memory": self.memory,
            "bucket": self.bucket,
        }

    @staticmethod
    def deserialize(cached_config: dict) -> "GCPWorkflow":
        from sebs.faas.function import Trigger
        from sebs.gcp.triggers import LibraryTrigger, HTTPTrigger

        ret = GCPWorkflow(
            cached_config["name"],
            cached_config["benchmark"],
            cached_config["hash"],
            cached_config["timeout"],
            cached_config["memory"],
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
            self.bucket, idx = storage_client.add_input_bucket(benchmark)
        return self.bucket
