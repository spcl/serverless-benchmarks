from typing import cast, Optional

from sebs.cache import Cache
from sebs.local.storage import Minio
from sebs.faas.resources import SystemResources
from sebs.faas.storage import PersistentStorage
from sebs.faas.nosql import NoSQLStorage
from sebs.local.config import LocalConfig, LocalResources
from sebs.utils import LoggingHandlers

import docker


class LocalSystemResources(SystemResources):
    def __init__(
        self,
        config: LocalConfig,
        cache_client: Cache,
        docker_client: docker.client,
        logger_handlers: LoggingHandlers,
    ):
        super().__init__(config, cache_client, docker_client)

        self._logging_handlers = logger_handlers
        self._storage: Optional[PersistentStorage] = None

    """
        Create wrapper object for minio storage and fill buckets.
        Starts minio as a Docker instance, using always fresh buckets.

        :param benchmark:
        :param buckets: number of input and output buckets
        :param replace_existing: not used.
        :return: Azure storage instance
    """

    def get_storage(self, replace_existing: Optional[bool] = None) -> PersistentStorage:
        if self._storage is None:

            storage_config = cast(LocalResources, self._config.resources).storage_config
            if storage_config is None:
                raise RuntimeError(
                    "The local deployment is missing the configuration of pre-allocated storage!"
                )

            self._storage = Minio.deserialize(
                storage_config,
                self._cache_client,
                self._config.resources,
            )
            self._storage.logging_handlers = self._logging_handlers
        elif replace_existing is not None:
            self._storage.replace_existing = replace_existing
        return self._storage

    def get_nosql_storage(self) -> NoSQLStorage:
        raise NotImplementedError()
