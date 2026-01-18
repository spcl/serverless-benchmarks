from typing import Optional, cast

from sebs.faas.function import Function, FunctionConfig


class CloudflareWorker(Function):
    """
    Cloudflare Workers function implementation.
    
    A Cloudflare Worker is a serverless function that runs on Cloudflare's edge network.
    """
    
    def __init__(
        self,
        name: str,
        benchmark: str,
        script_id: str,
        code_package_hash: str,
        runtime: str,
        cfg: FunctionConfig,
        account_id: Optional[str] = None,
    ):
        super().__init__(benchmark, name, code_package_hash, cfg)
        self.script_id = script_id
        self.runtime = runtime
        self.account_id = account_id

    @staticmethod
    def typename() -> str:
        return "Cloudflare.Worker"

    def serialize(self) -> dict:
        return {
            **super().serialize(),
            "script_id": self.script_id,
            "runtime": self.runtime,
            "account_id": self.account_id,
        }

    @staticmethod
    def deserialize(cached_config: dict) -> "CloudflareWorker":
        from sebs.faas.function import Trigger
        from sebs.cloudflare.triggers import HTTPTrigger

        cfg = FunctionConfig.deserialize(cached_config["config"])
        ret = CloudflareWorker(
            cached_config["name"],
            cached_config["benchmark"],
            cached_config["script_id"],
            cached_config["hash"],
            cached_config["runtime"],
            cfg,
            cached_config.get("account_id"),
        )
        
        for trigger in cached_config["triggers"]:
            trigger_type = HTTPTrigger if trigger["type"] == HTTPTrigger.typename() else None
            assert trigger_type, "Unknown trigger type {}".format(trigger["type"])
            ret.add_trigger(trigger_type.deserialize(trigger))
        
        return ret
