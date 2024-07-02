from __future__ import annotations

from typing import cast, Optional
from dataclasses import dataclass

from sebs.benchmark import Benchmark
from sebs.faas.function import Function, FunctionConfig, Runtime
from sebs.storage.config import MinioConfig

@dataclass
class KnativeFunctionConfig(FunctionConfig):
    docker_image: str = ""
    namespace: str = "default"
    storage: Optional[MinioConfig] = None
    url: str = ""

    @staticmethod
    def deserialize(data: dict) -> KnativeFunctionConfig:
        keys = list(KnativeFunctionConfig.__dataclass_fields__.keys())
        data = {k: v for k, v in data.items() if k in keys}
        data["runtime"] = Runtime.deserialize(data["runtime"])
        data["storage"] = MinioConfig.deserialize(data["storage"])
        return KnativeFunctionConfig(**data)

    def serialize(self) -> dict:
        return self.__dict__

    @staticmethod
    def from_benchmark(benchmark: Benchmark) -> KnativeFunctionConfig:
        return super(KnativeFunctionConfig, KnativeFunctionConfig)._from_benchmark(
            benchmark, KnativeFunctionConfig
        )

class KnativeFunction(Function):
    def __init__(
        self, name: str, benchmark: str, code_package_hash: str, cfg: KnativeFunctionConfig
    ):
        super().__init__(benchmark, name, code_package_hash, cfg)

    @property
    def config(self) -> KnativeFunctionConfig:
        return cast(KnativeFunctionConfig, self._cfg)

    @staticmethod
    def typename() -> str:
        return "Knative.Function"

    def serialize(self) -> dict:
        return {**super().serialize(), "config": self._cfg.serialize()}

    @staticmethod
    def deserialize(cached_config: dict) -> KnativeFunction:
        from sebs.faas.function import Trigger
        from sebs.knative.triggers import KnativeLibraryTrigger, KnativeHTTPTrigger

        cfg = KnativeFunctionConfig.deserialize(cached_config["config"])
        ret = KnativeFunction(
            cached_config["name"], cached_config["benchmark"], cached_config["hash"], cfg
        )
        for trigger in cached_config["triggers"]:
            trigger_type = cast(
                Trigger,
                {"Library": KnativeLibraryTrigger, "HTTP": KnativeHTTPTrigger}.get(trigger["type"]),
            )
            assert trigger_type, "Unknown trigger type {}".format(trigger["type"])
            ret.add_trigger(trigger_type.deserialize(trigger))
        return ret
