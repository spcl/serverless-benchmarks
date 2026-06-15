"""Cloudflare Workflow representation for SeBS."""

from typing import List

from sebs.cloudflare.function import CloudflareWorker
from sebs.faas.function import FunctionConfig, Workflow


class CloudflareWorkflow(Workflow):
    """Represents a deployed Cloudflare Workflow with its dispatcher and orchestrator."""

    def __init__(
        self,
        name: str,
        functions: List[CloudflareWorker],
        benchmark: str,
        code_package_hash: str,
        cfg: FunctionConfig,
        account_id: str,
        dispatcher_name: str,
        orchestrator_url: str,
    ):
        """Initialize a CloudflareWorkflow.

        Args:
            name: Workflow name (also the orchestrator worker name).
            functions: List of dispatcher CloudflareWorker instances.
            benchmark: Benchmark identifier.
            code_package_hash: Hash of the deployed code package.
            cfg: Function configuration (memory, timeout).
            account_id: Cloudflare account ID.
            dispatcher_name: Name of the dispatcher worker/container.
            orchestrator_url: URL of the orchestrator worker.
        """
        super().__init__(benchmark, name, code_package_hash, cfg)
        self.functions = functions
        self.account_id = account_id
        self.dispatcher_name = dispatcher_name
        self.orchestrator_url = orchestrator_url

    @staticmethod
    def typename() -> str:
        """Return the canonical type name for this workflow class."""
        return "Cloudflare.Workflow"

    def serialize(self) -> dict:
        """Serialize workflow state for caching."""
        return {
            **super().serialize(),
            "functions": [f.serialize() for f in self.functions],
            "account_id": self.account_id,
            "dispatcher_name": self.dispatcher_name,
            "orchestrator_url": self.orchestrator_url,
        }

    @staticmethod
    def deserialize(cached_config: dict) -> "CloudflareWorkflow":
        """Reconstruct a CloudflareWorkflow from a cached configuration dict."""
        from sebs.cloudflare.triggers import HTTPTrigger, WorkflowLibraryTrigger

        funcs = [CloudflareWorker.deserialize(f) for f in cached_config["functions"]]
        cfg = FunctionConfig.deserialize(cached_config["config"])

        ret = CloudflareWorkflow(
            cached_config["name"],
            funcs,
            cached_config["benchmark"],
            cached_config["hash"],
            cfg,
            cached_config["account_id"],
            cached_config["dispatcher_name"],
            cached_config["orchestrator_url"],
        )

        for trigger in cached_config["triggers"]:
            if trigger["type"] == WorkflowLibraryTrigger.typename():
                ret.add_trigger(WorkflowLibraryTrigger.deserialize(trigger))
            elif trigger["type"] == HTTPTrigger.typename():
                ret.add_trigger(HTTPTrigger.deserialize(trigger))

        return ret
