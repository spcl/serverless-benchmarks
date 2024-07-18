from __future__ import annotations

from typing import cast, Optional
from dataclasses import dataclass

from sebs.benchmark import Benchmark
from sebs.faas.function import Function, FunctionConfig, Runtime
from sebs.storage.config import MinioConfig


@dataclass
class FissionFunctionConfig(FunctionConfig):

    # FIXME: merge with higher level abstraction for images
    docker_image: str = ""
    namespace: str = "_"
    storage: Optional[MinioConfig] = None

    @staticmethod
    def deserialize(data: dict) -> FissionFunctionConfig:
        keys = list(FissionFunctionConfig.__dataclass_fields__.keys())
        data = {k: v for k, v in data.items() if k in keys}
        data["runtime"] = Runtime.deserialize(data["runtime"])
        data["storage"] = MinioConfig.deserialize(data["storage"])
        return FissionFunctionConfig(**data)

    def serialize(self) -> dict:
        return self.__dict__

    @staticmethod
    def from_benchmark(benchmark: Benchmark) -> FissionFunctionConfig:
        return super(FissionFunctionConfig, FissionFunctionConfig)._from_benchmark(
            benchmark, FissionFunctionConfig 
        )


class FissionFunction(Function):
    def __init__(
        self, name: str, benchmark: str, code_package_hash: str, cfg: FissionFunctionConfig 
    ):
        super().__init__(benchmark, name, code_package_hash, cfg)

    @property
    def config(self) -> FissionFunctionConfig:
        return cast(FissionFunctionConfig, self._cfg)

    @staticmethod
    def typename() -> str:
        return "Fission.Function"

    def serialize(self) -> dict:
        return {**super().serialize(), "config": self._cfg.serialize()}

    @staticmethod
    def deserialize(cached_config: dict) -> FissionFunction:
        from sebs.faas.function import Trigger
        from sebs.fission.triggers import LibraryTrigger, HTTPTrigger

        cfg = FissionFunctionConfig.deserialize(cached_config["config"])
        ret = FissionFunction(
            cached_config["name"], cached_config["benchmark"], cached_config["hash"], cfg
        )
        for trigger in cached_config["triggers"]:
            trigger_type = cast(
                Trigger,
                {"Library": LibraryTrigger, "HTTP": HTTPTrigger}.get(trigger["type"]),
            )
            assert trigger_type, "Unknown trigger type {}".format(trigger["type"])
            ret.add_trigger(trigger_type.deserialize(trigger))
        return ret

