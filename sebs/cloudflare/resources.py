import docker

from typing import Optional

from sebs.cache import Cache
from sebs.cloudflare.config import CloudflareConfig
from sebs.faas.resources import SystemResources
from sebs.faas.storage import PersistentStorage
from sebs.faas.nosql import NoSQLStorage
from sebs.utils import LoggingHandlers


class CloudflareSystemResources(SystemResources):
    """
    System resources for Cloudflare Workers.
    
    Cloudflare Workers have a different resource model compared to
    traditional cloud platforms. This class handles Cloudflare-specific
    resources like KV namespaces and R2 storage.
    """
    
    def __init__(
        self,
        config: CloudflareConfig,
        cache_client: Cache,
        docker_client: docker.client,
        logging_handlers: LoggingHandlers,
    ):
        super().__init__(config, cache_client, docker_client, logging_handlers)
        self._config = config

    @property
    def config(self) -> CloudflareConfig:
        return self._config

    def get_storage(self, replace_existing: Optional[bool] = None) -> PersistentStorage:
        """
        Get Cloudflare R2 storage instance.
        
        R2 is Cloudflare's S3-compatible object storage service.
        This method will create a client for managing benchmark input/output data.
        
        Args:
            replace_existing: Whether to replace existing files in storage
            
        Raises:
            NotImplementedError: R2 storage support not yet implemented
        """
        raise NotImplementedError(
            "Cloudflare R2 storage is not yet implemented. "
            "To add support, implement a PersistentStorage subclass for R2 "
            "similar to sebs/aws/s3.py or sebs/azure/blob_storage.py"
        )

    def get_nosql_storage(self) -> NoSQLStorage:
        """
        Get Cloudflare NoSQL storage instance.
        
        This could use Cloudflare D1 (SQLite) or Durable Objects for NoSQL storage.
        
        Raises:
            NotImplementedError: NoSQL storage support not yet implemented
        """
        raise NotImplementedError(
            "Cloudflare NoSQL storage (D1/Durable Objects) is not yet implemented. "
            "To add support, implement a NoSQLStorage subclass "
            "similar to sebs/aws/dynamodb.py or sebs/azure/cosmosdb.py"
        )
