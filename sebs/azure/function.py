from sebs.azure.config import AzureResources
from sebs.faas.function import Function, FunctionConfig


class AzureFunction(Function):
    def __init__(
        self,
        name: str,
        benchmark: str,
        code_hash: str,
        function_storage: AzureResources.Storage,
        cfg: FunctionConfig,
    ):
        super().__init__(benchmark, name, code_hash, cfg)
        self.function_storage = function_storage

    def serialize(self) -> dict:
        return {
            **super().serialize(),
            "function_storage": self.function_storage.serialize(),
        }

    @staticmethod
    def deserialize(cached_config: dict) -> Function:
        cfg = FunctionConfig.deserialize(cached_config["config"])
        ret = AzureFunction(
            cached_config["name"],
            cached_config["benchmark"],
            cached_config["hash"],
            AzureResources.Storage.deserialize(cached_config["function_storage"]),
            cfg,
        )
        from sebs.azure.triggers import HTTPTrigger

        for trigger in cached_config["triggers"]:
            trigger_type = {"HTTP": HTTPTrigger}.get(trigger["type"])
            assert trigger_type, "Unknown trigger type {}".format(trigger["type"])
            ret.add_trigger(trigger_type.deserialize(trigger))
        return ret
