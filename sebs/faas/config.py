from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from enum import Enum
from typing import Dict, Optional

from sebs.cache import Cache
from sebs.utils import has_platform, LoggingBase, LoggingHandlers

# FIXME: Replace type hints for static generators after migration to 3.7
# https://stackoverflow.com/questions/33533148/how-do-i-specify-that-the-return-type-of-a-method-is-the-same-as-the-class-itsel

"""
    Credentials for FaaS system used to authorize operations on functions
    and other resources.

    The order of credentials initialization:
    1. Load credentials from cache.
    2. If any new values are provided in the config, they override cache values.
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
    class StorageBucketType(str, Enum):
        DEPLOYMENT = "deployment"
        BENCHMARKS = "benchmarks"
        EXPERIMENTS = "experiments"

        @staticmethod
        def deserialize(val: str) -> Resources.StorageBucketType:
            for member in Resources.StorageBucketType:
                if member.value == val:
                    return member
            raise Exception(f"Unknown storage bucket type type {val}")

    def __init__(self, name: str):
        super().__init__()
        self._name = name
        self._buckets: Dict[Resources.StorageBucketType, str] = {}
        self._resources_id: Optional[str] = None

    @property
    def resources_id(self) -> str:
        assert self._resources_id is not None
        return self._resources_id

    @resources_id.setter
    def resources_id(self, resources_id: str):
        self._resources_id = resources_id

    @property
    def has_resources_id(self) -> bool:
        return self._resources_id is not None

    @property
    def region(self) -> str:
        return self._region

    @region.setter
    def region(self, region: str):
        self._region = region

    def get_storage_bucket(self, bucket_type: Resources.StorageBucketType) -> Optional[str]:
        return self._buckets.get(bucket_type)

    def get_storage_bucket_name(self, bucket_type: Resources.StorageBucketType) -> str:
        return f"sebs-{bucket_type.value}-{self._resources_id}"

    def set_storage_bucket(self, bucket_type: Resources.StorageBucketType, bucket_name: str):
        self._buckets[bucket_type] = bucket_name

    @staticmethod
    @abstractmethod
    def initialize(res: Resources, dct: dict):

        if "resources_id" in dct:
            res._resources_id = dct["resources_id"]

        if "storage_buckets" in dct:
            for key, value in dct["storage_buckets"].items():
                res._buckets[Resources.StorageBucketType.deserialize(key)] = value

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

    @abstractmethod
    def serialize(self) -> dict:
        out = {}
        if self.has_resources_id:
            out["resources_id"] = self.resources_id
        for key, value in self._buckets.items():
            out[key.value] = value
        return out

    def update_cache(self, cache: Cache):
        if self.has_resources_id:
            cache.update_config(
                val=self.resources_id, keys=[self._name, "resources", "resources_id"]
            )
        for key, value in self._buckets.items():
            cache.update_config(
                val=value, keys=[self._name, "resources", "storage_buckets", key.value]
            )


"""
    FaaS system config defining cloud region (if necessary), credentials and
    resources allocated.
"""


class Config(ABC, LoggingBase):

    _region: str

    def __init__(self, name: str):
        super().__init__()
        self._region = ""
        self._name = name

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
    def initialize(cfg: Config, dct: dict):
        cfg._region = dct["region"]

    @staticmethod
    @abstractmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Config:
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
        
        # Cloudflare is available by default (like local)
        try:
            from sebs.cloudflare.config import CloudflareConfig
            implementations["cloudflare"] = CloudflareConfig.deserialize
        except ImportError:
            pass
        
        func = implementations.get(name)
        assert func, "Unknown config type!"
        return func(config[name] if name in config else config, cache, handlers)

    @abstractmethod
    def serialize(self) -> dict:
        return {"name": self._name, "region": self._region}

    @abstractmethod
    def update_cache(self, cache: Cache):
        cache.update_config(val=self.region, keys=[self._name, "region"])
