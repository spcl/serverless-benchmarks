from sebs.azure.config import AzureResources
from sebs.faas.function import Function


class AzureFunction(Function):
    def __init__(
        self, name: str, code_hash: str, function_storage: AzureResources.Storage
    ):
        super().__init__(name, code_hash)
        self.function_storage = function_storage

    def serialize(self) -> dict:
        return {
            **super().serialize(),
            "function_storage": self.function_storage.serialize(),
        }

    @staticmethod
    def deserialize(cached_config: dict) -> Function:
        ret = AzureFunction(
            cached_config["name"],
            cached_config["hash"],
            AzureResources.Storage.deserialize(cached_config["function_storage"]),
        )
        from sebs.azure.triggers import HTTPTrigger

        for trigger in cached_config["triggers"]:
            trigger_type = {"HTTP": HTTPTrigger}.get(trigger["type"])
            assert trigger_type, "Unknown trigger type {}".format(trigger["type"])
            ret.add_trigger(trigger_type.deserialize(trigger))
        return ret
