from sebs.azure.config import AzureResources
from sebs.faas.function import Function, ExecutionResult


class AzureFunction(Function):
    def __init__(self, name: str):
        super().__init__(name)

    def sync_invoke(self, payload: dict) -> ExecutionResult:
        raise NotImplementedError(
            " Client-side invocation not supported for Azure Functions. "
            " Please use triggers instead! "
        )

    def async_invoke(self, payload: dict) -> ExecutionResult:
        raise NotImplementedError(
            " Client-side invocation not supported for Azure Functions. "
            " Please use triggers instead! "
        )

    @staticmethod
    def deserialize(
        cached_config: dict, data_storage_account: AzureResources.Storage
    ) -> Function:
        ret = AzureFunction(cached_config["name"])
        from sebs.azure.triggers import HTTPTrigger

        # FIXME: remove after fixing cache
        ret.add_trigger(HTTPTrigger(cached_config["invoke_url"], data_storage_account))

        # FIXME: reenableafter fixing cache
        # for trigger in cached_config["triggers"]:
        #    trigger_type = {"HTTP": HTTPTrigger}.get(trigger["type"])
        #    assert trigger_type, "Unknown trigger type {}".format(trigger["type"])
        #    ret.add_trigger(trigger_type.deserialize(trigger))
        return ret
