from sebs.faas.function import Function
from typing import cast


class OpenwhiskFunction(Function):
    def __init__(
        self,
        name: str,
        benchmark: str,
        code_package_hash: str,
        docker_image: str,
        namespace: str = "_",
    ):
        super().__init__(benchmark, name, code_package_hash)
        self.namespace = namespace
        self.docker_image = docker_image

    @staticmethod
    def typename() -> str:
        return "OpenWhisk.Function"

    def serialize(self) -> dict:
        return {**super().serialize(), "namespace": self.namespace, "image": self.docker_image}

    @staticmethod
    def deserialize(cached_config: dict) -> "OpenwhiskFunction":
        from sebs.faas.function import Trigger
        from sebs.openwhisk.triggers import LibraryTrigger, HTTPTrigger

        ret = OpenwhiskFunction(
            cached_config["name"],
            cached_config["benchmark"],
            cached_config["hash"],
            cached_config["image"],
            cached_config["namespace"],
        )
        for trigger in cached_config["triggers"]:
            trigger_type = cast(
                Trigger,
                {"Library": LibraryTrigger, "HTTP": HTTPTrigger}.get(trigger["type"]),
            )
            assert trigger_type, "Unknown trigger type {}".format(trigger["type"])
            ret.add_trigger(trigger_type.deserialize(trigger))
        return ret
