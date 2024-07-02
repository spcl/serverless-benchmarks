import docker
from sebs.faas.config import Resources
from sebs.storage import minio
from sebs.storage.config import MinioConfig
from sebs.cache import Cache

class KnativeMinio(minio.Minio):
    @staticmethod
    def deployment_name() -> str:
        return "knative"

    def __init__(
        self,
        docker_client: docker.client,
        cache_client: Cache,
        res: Resources,
        replace_existing: bool,
    ):
        super().__init__(docker_client, cache_client, res, replace_existing)

    @staticmethod
    def deserialize(
        cached_config: MinioConfig, cache_client: Cache, resources: Resources
    ) -> "KnativeMinio":
        return super(KnativeMinio, KnativeMinio)._deserialize(cached_config, cache_client, resources, KnativeMinio)
