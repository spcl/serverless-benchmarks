from abc import ABC
from abc import abstractmethod
from typing import List, Optional

from sebs.cache import Cache
from sebs.utils import has_platform, LoggingBase, LoggingHandlers

# FIXME: Replace type hints for static generators after migration to 3.7
# https://stackoverflow.com/questions/33533148/how-do-i-specify-that-the-return-type-of-a-method-is-the-same-as-the-class-itsel

"""
    Credentials for FaaS system used to authorize operations on functions
    and other resources.

    The order of credentials initialization:
    1. Load credentials from cache.
    2. If any new vaues are provided in the config, they override cache values.
    3. If nothing is provided, initialize using environmental variables.
    4. If no information is provided, then failure is reported.
"""


class Credentials(ABC, LoggingBase):
    def __init__(self):
        super().__init__()

    """
        Create credentials instance from user config and cached values.
    """

    @staticmethod
    @abstractmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> "Credentials":
        pass

    """
        Serialize to JSON for storage in cache.
    """

    @abstractmethod
    def serialize(self) -> dict:
        pass


"""
    Class grouping resources allocated at the FaaS system to execute functions
    and deploy various services. Examples might include IAM roles and API gateways
    for HTTP triggers.

    Storage resources are handled seperately.
"""


class Resources(ABC, LoggingBase):
    def __init__(self):
        super().__init__()
        self._redis_host: Optional[str] = None
        self._redis_password: Optional[str] = None

    """
        Create credentials instance from user config and cached values.
    """

    @staticmethod
    @abstractmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> "Resources":
        pass

    """
        Serialize to JSON for storage in cache.
    """

    def serialize(self) -> dict:
        if self._redis_host is not None:
            return {"redis": {"host": self._redis_host, "password": self._redis_password}}
        else:
            return {}

    def load_redis(self, config: dict):
        if "redis" in config:
            self._redis_host = config["redis"]["host"]
            self._redis_password = config["redis"]["password"]

    def update_cache_redis(self, keys: List[str], cache: Cache):
        if self._redis_host is not None:
            cache.update_config(val=self._redis_host, keys=[*keys, "redis", "host"])
            cache.update_config(val=self._redis_password, keys=[*keys, "redis", "password"])

    @property
    def redis_host(self) -> Optional[str]:
        return self._redis_host

    @property
    def redis_password(self) -> Optional[str]:
        return self._redis_password


"""
    FaaS system config defining cloud region (if necessary), credentials and
    resources allocated.
"""


class Config(ABC, LoggingBase):

    _region: str

    def __init__(self):
        super().__init__()

    @property
    def region(self) -> str:
        return self._region

    @property
    @abstractmethod
    def credentials(self) -> Credentials:
        pass

    @property
    @abstractmethod
    def resources(self) -> Resources:
        pass

    @staticmethod
    @abstractmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> "Config":
        from sebs.local.config import LocalConfig

        name = config["name"]
        implementations = {"local": LocalConfig.deserialize}
        if has_platform("aws"):
            from sebs.aws.config import AWSConfig

            implementations["aws"] = AWSConfig.deserialize
        if has_platform("azure"):
            from sebs.azure.config import AzureConfig

            implementations["azure"] = AzureConfig.deserialize
        if has_platform("gcp"):
            from sebs.gcp.config import GCPConfig

            implementations["gcp"] = GCPConfig.deserialize
        if has_platform("openwhisk"):
            from sebs.openwhisk.config import OpenWhiskConfig

            implementations["openwhisk"] = OpenWhiskConfig.deserialize
        func = implementations.get(name)
        assert func, "Unknown config type!"
        return func(config[name] if name in config else config, cache, handlers)

    @abstractmethod
    def serialize(self) -> dict:
        pass

    @abstractmethod
    def update_cache(self, cache: Cache):
        pass
