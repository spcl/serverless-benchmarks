from sebs.azure.config import AzureResources
from sebs.faas import function
from sebs.faas.function import CloudBenchmark, FunctionConfig

from typing import cast


class Function(CloudBenchmark):
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
    def deserialize(cached_config: dict) -> function.CloudBenchmark:
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


class AzureFunction(function.Function, Function):
    @staticmethod
    def deserialize(cached_config: dict) -> "AzureFunction":
        return cast(AzureFunction, AzureFunction.deserialize(cached_config))


class AzureWorkflow(function.Workflow, Function):
    @staticmethod
    def deserialize(cached_config: dict) -> "AzureWorkflow":
        return cast(AzureWorkflow, AzureFunction.deserialize(cached_config))
