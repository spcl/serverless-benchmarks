from __future__ import annotations

from typing import cast, Optional
from dataclasses import dataclass

from sebs.benchmark import Benchmark
from sebs.faas.function import Function, FunctionConfig, Runtime
from sebs.storage.config import MinioConfig


@dataclass
class OpenWhiskFunctionConfig(FunctionConfig):

    # FIXME: merge with higher level abstraction for images
    docker_image: str = ""
    namespace: str = "_"
    storage: Optional[MinioConfig] = None

    @staticmethod
    def deserialize(data: dict) -> OpenWhiskFunctionConfig:
        keys = list(OpenWhiskFunctionConfig.__dataclass_fields__.keys())
        data = {k: v for k, v in data.items() if k in keys}
        data["runtime"] = Runtime.deserialize(data["runtime"])
        data["storage"] = MinioConfig.deserialize(data["storage"])
        return OpenWhiskFunctionConfig(**data)

    def serialize(self) -> dict:
        return self.__dict__

    @staticmethod
    def from_benchmark(benchmark: Benchmark) -> OpenWhiskFunctionConfig:
        return super(OpenWhiskFunctionConfig, OpenWhiskFunctionConfig)._from_benchmark(
            benchmark, OpenWhiskFunctionConfig
        )


class OpenWhiskFunction(Function):
    def __init__(
        self, name: str, benchmark: str, code_package_hash: str, cfg: OpenWhiskFunctionConfig
    ):
        super().__init__(benchmark, name, code_package_hash, cfg)

    @property
    def config(self) -> OpenWhiskFunctionConfig:
        return cast(OpenWhiskFunctionConfig, self._cfg)

    @staticmethod
    def typename() -> str:
        return "OpenWhisk.Function"

    def serialize(self) -> dict:
        return {**super().serialize(), "config": self._cfg.serialize()}

    @staticmethod
    def deserialize(cached_config: dict) -> OpenWhiskFunction:
        from sebs.faas.function import Trigger
        from sebs.openwhisk.triggers import LibraryTrigger, HTTPTrigger

        cfg = OpenWhiskFunctionConfig.deserialize(cached_config["config"])
        ret = OpenWhiskFunction(
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
