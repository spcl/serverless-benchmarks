import docker

from typing import Optional

from sebs.cache import Cache
from sebs.cloudflare.config import CloudflareConfig
from sebs.cloudflare.r2 import R2
from sebs.cloudflare.kvstore import KVStore
from sebs.faas.resources import SystemResources
from sebs.faas.storage import PersistentStorage
from sebs.faas.nosql import NoSQLStorage
from sebs.utils import LoggingHandlers
import json


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
        super().__init__(config, cache_client, docker_client)
        self._config = config
        self.logging_handlers = logging_handlers

    @property
    def config(self) -> CloudflareConfig:
        return self._config

    def _get_auth_headers(self) -> dict[str, str]:
        """Get authentication headers for Cloudflare API requests."""
        if self._config.credentials.api_token:
            return {
                "Authorization": f"Bearer {self._config.credentials.api_token}",
                "Content-Type": "application/json",
            }
        elif self._config.credentials.email and self._config.credentials.api_key:
            return {
                "X-Auth-Email": self._config.credentials.email,
                "X-Auth-Key": self._config.credentials.api_key,
                "Content-Type": "application/json",
            }
        else:
            raise RuntimeError("Invalid Cloudflare credentials configuration")

    def get_storage(self, replace_existing: Optional[bool] = None) -> PersistentStorage:
        """
        Get Cloudflare R2 storage instance.

        R2 is Cloudflare's S3-compatible object storage service.
        This method will create a client for managing benchmark input/output data.

        Args:
            replace_existing: Whether to replace existing files in storage

        Returns:
            R2 storage instance
        """
        if replace_existing is None:
            replace_existing = False

        return R2(
            region=self._config.region,
            cache_client=self._cache_client,
            resources=self._config.resources,
            replace_existing=replace_existing,
            credentials=self._config.credentials,
        )

    def get_nosql_storage(self) -> NoSQLStorage:
        """
        Get Cloudflare KV storage instance.

        KV namespaces provide key-value storage for Workers.

        Returns:
            KVStore storage instance
        """
        return KVStore(
            region=self._config.region,
            cache_client=self._cache_client,
            resources=self._config.resources,
            credentials=self._config.credentials,
        )
