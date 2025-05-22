from sebs.azure.config import AzureResources
from sebs.faas.function import Function, FunctionConfig


class AzureFunction(Function):
    """
    Represents an Azure Function.

    Extends the base Function class with Azure-specific attributes like the
    storage account associated with the function's code.
    """
    def __init__(
        self,
        name: str,
        benchmark: str,
        code_hash: str,
        function_storage: AzureResources.Storage,
        cfg: FunctionConfig,
    ):
        """
        Initialize an AzureFunction instance.

        :param name: Name of the Azure Function app.
        :param benchmark: Name of the benchmark this function belongs to.
        :param code_hash: Hash of the deployed code package.
        :param function_storage: AzureResources.Storage instance for the function's code storage.
        :param cfg: FunctionConfig object with memory, timeout, etc.
        """
        super().__init__(benchmark, name, code_hash, cfg)
        self.function_storage = function_storage

    def serialize(self) -> dict:
        """
        Serialize the AzureFunction instance to a dictionary.

        Includes Azure-specific attributes (function_storage) along with base
        Function attributes.

        :return: Dictionary representation of the AzureFunction.
        """
        return {
            **super().serialize(),
            "function_storage": self.function_storage.serialize(),
        }

    @staticmethod
    def deserialize(cached_config: dict) -> Function:
        """
        Deserialize an AzureFunction instance from a dictionary.

        Typically used when loading function details from a cache.

        :param cached_config: Dictionary containing serialized AzureFunction data.
        :return: A new AzureFunction instance.
        """
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
