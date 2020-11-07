from typing import cast

from sebs.faas.function import Function


class GCPFunction(Function):
    def __init__(self, name: str, benchmark: str, code_package_hash: str):
        super().__init__(benchmark, name, code_package_hash)

    @staticmethod
    def typename() -> str:
        return "GCP.GCPFunction"

    def serialize(self) -> dict:
        return super().serialize()

    @staticmethod
    def deserialize(cached_config: dict) -> "GCPFunction":
        from sebs.faas.function import Trigger
        from sebs.gcp.triggers import LibraryTrigger, HTTPTrigger

        ret = GCPFunction(
            cached_config["name"], cached_config["benchmark"], cached_config["hash"]
        )
        for trigger in cached_config["triggers"]:
            trigger_type = cast(
                Trigger,
                {"Library": LibraryTrigger, "HTTP": HTTPTrigger}.get(trigger["type"]),
            )
            assert trigger_type, "Unknown trigger type {}".format(trigger["type"])
            ret.add_trigger(trigger_type.deserialize(trigger))
        return ret
