from typing import cast, List

from dataclasses import dataclass, field

from sebs.cache import Cache
from sebs.faas.config import Resources


class MinioResources(Resources):
    def __init__(self):
        super().__init__(name="minio")

    @staticmethod
    def initialize(res: Resources, dct: dict):
        ret = cast(MinioResources, res)
        super(MinioResources, MinioResources).initialize(ret, dct)
        return ret

    def serialize(self) -> dict:
        return super().serialize()

    @staticmethod
    def deserialize(config: dict) -> "Resources":  # type: ignore

        ret = MinioResources()
        MinioResources.initialize(ret, {})
        return ret

    def update_cache(self, cache: Cache):
        super().update_cache(cache)


@dataclass
class MinioConfig:
    address: str = ""
    mapped_port: int = -1
    access_key: str = ""
    secret_key: str = ""
    instance_id: str = ""
    output_buckets: List[str] = field(default_factory=list)
    input_buckets: List[str] = field(default_factory=lambda: [])
    type: str = "minio"

    def update_cache(self, path: List[str], cache: Cache):

        for key in MinioConfig.__dataclass_fields__.keys():
            if key == "resources":
                continue
            cache.update_config(val=getattr(self, key), keys=[*path, key])
        # self.resources.update_cache(cache)

    @staticmethod
    def deserialize(data: dict) -> "MinioConfig":
        keys = list(MinioConfig.__dataclass_fields__.keys())
        data = {k: v for k, v in data.items() if k in keys}

        cfg = MinioConfig(**data)
        # cfg.resources = cast(MinioResources, MinioResources.deserialize(data["resources"]))

        return cfg

    def serialize(self) -> dict:
        return self.__dict__  # , "resources": self.resources.serialize()}
