import docker

from sebs.storage import minio
from sebs.storage.config import MinioConfig
from sebs.cache import Cache


class Minio(minio.Minio):
    @staticmethod
    def deployment_name() -> str:
        return "openwhisk"

    def __init__(self, docker_client: docker.client, cache_client: Cache, replace_existing: bool):
        super().__init__(docker_client, cache_client, replace_existing)

    @staticmethod
    def deserialize(cached_config: MinioConfig, cache_client: Cache) -> "Minio":
        return super(Minio, Minio)._deserialize(cached_config, cache_client, Minio)
