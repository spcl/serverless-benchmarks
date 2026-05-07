"""Cloudflare system resources manager."""

import docker
from typing import Optional, cast

from sebs.cache import Cache
from sebs.cloudflare.config import CloudflareConfig, CloudflareCredentials
from sebs.cloudflare.r2 import R2
from sebs.cloudflare.kvstore import KVStore
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
        docker_client: docker.client.DockerClient,
        logging_handlers: LoggingHandlers,
    ):
        """Initialize Cloudflare system resources with config and logging handlers."""
        super().__init__(config, cache_client, docker_client)
        self._config = config
        self.logging_handlers = logging_handlers

    @property
    def config(self) -> CloudflareConfig:
        """Return the Cloudflare-specific platform configuration."""
        return cast(CloudflareConfig, self._config)

    def _get_auth_headers(self) -> dict[str, str]:
        """Get authentication headers for Cloudflare API requests."""
        credentials = cast(CloudflareCredentials, self._config.credentials)
        if credentials.api_token:
            return {
                "Authorization": f"Bearer {credentials.api_token}",
                "Content-Type": "application/json",
            }
        elif credentials.email and credentials.api_key:
            return {
                "X-Auth-Email": credentials.email,
                "X-Auth-Key": credentials.api_key,
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
            credentials=cast(CloudflareCredentials, self._config.credentials),
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
            credentials=cast(CloudflareCredentials, self._config.credentials),
        )
