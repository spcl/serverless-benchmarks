from typing import List

from dataclasses import dataclass, field

from sebs.cache import Cache


@dataclass
class MinioConfig:
    address: str = ""
    mapped_port: int = -1
    access_key: str = ""
    secret_key: str = ""
    instance_id: str = ""
    input_buckets: List[str] = field(default_factory=list)
    output_buckets: List[str] = field(default_factory=list)
    type: str = "minio"

    def update_cache(self, path: List[str], cache: Cache):
        for key in MinioConfig.__dataclass_fields__.keys():
            cache.update_config(val=getattr(self, key), keys=[*path, key])

    @staticmethod
    def deserialize(data: dict) -> "MinioConfig":
        keys = list(MinioConfig.__dataclass_fields__.keys())
        data = {k: v for k, v in data.items() if k in keys}
        return MinioConfig(**data)

    def serialize(self) -> dict:
        return self.__dict__
