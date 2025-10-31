import os
from typing import Optional, cast

from sebs.cache import Cache
from sebs.faas.config import Config, Credentials, Resources
from sebs.utils import LoggingHandlers


class CloudflareCredentials(Credentials):
    """
    Cloudflare API credentials.
    
    Requires:
    - API token or email + global API key
    - Account ID
    """
    
    def __init__(self, api_token: Optional[str] = None, email: Optional[str] = None, 
                 api_key: Optional[str] = None, account_id: Optional[str] = None):
        super().__init__()
        
        self._api_token = api_token
        self._email = email
        self._api_key = api_key
        self._account_id = account_id

    @staticmethod
    def typename() -> str:
        return "Cloudflare.Credentials"

    @property
    def api_token(self) -> Optional[str]:
        return self._api_token

    @property
    def email(self) -> Optional[str]:
        return self._email

    @property
    def api_key(self) -> Optional[str]:
        return self._api_key

    @property
    def account_id(self) -> Optional[str]:
        return self._account_id

    @staticmethod
    def initialize(dct: dict) -> "CloudflareCredentials":
        return CloudflareCredentials(
            dct.get("api_token"),
            dct.get("email"),
            dct.get("api_key"),
            dct.get("account_id")
        )

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Credentials:
        cached_config = cache.get_config("cloudflare")
        ret: CloudflareCredentials
        account_id: Optional[str] = None

        # Load cached values
        if cached_config and "credentials" in cached_config:
            account_id = cached_config["credentials"].get("account_id")

        # Check for new config
        if "credentials" in config:
            ret = CloudflareCredentials.initialize(config["credentials"])
        elif "CLOUDFLARE_API_TOKEN" in os.environ:
            ret = CloudflareCredentials(
                api_token=os.environ["CLOUDFLARE_API_TOKEN"],
                account_id=os.environ.get("CLOUDFLARE_ACCOUNT_ID")
            )
        elif "CLOUDFLARE_EMAIL" in os.environ and "CLOUDFLARE_API_KEY" in os.environ:
            ret = CloudflareCredentials(
                email=os.environ["CLOUDFLARE_EMAIL"],
                api_key=os.environ["CLOUDFLARE_API_KEY"],
                account_id=os.environ.get("CLOUDFLARE_ACCOUNT_ID")
            )
        else:
            raise RuntimeError(
                "Cloudflare login credentials are missing! Please set "
                "up environmental variables CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID, "
                "or CLOUDFLARE_EMAIL, CLOUDFLARE_API_KEY, and CLOUDFLARE_ACCOUNT_ID"
            )

        if account_id is not None and ret.account_id is not None and account_id != ret.account_id:
            ret.logging.error(
                f"The account id {ret.account_id} from provided credentials is different "
                f"from the account id {account_id} found in the cache! Please change "
                "your cache directory or create a new one!"
            )
            raise RuntimeError(
                f"Cloudflare login credentials do not match the account {account_id} in cache!"
            )
        
        ret.logging_handlers = handlers
        return ret

    def update_cache(self, cache: Cache):
        if self._account_id:
            cache.update_config(val=self._account_id, 
                              keys=["cloudflare", "credentials", "account_id"])

    def serialize(self) -> dict:
        out = {}
        if self._account_id:
            out["account_id"] = self._account_id
        return out


class CloudflareResources(Resources):
    """
    Resources for Cloudflare Workers deployment.
    """
    
    def __init__(self):
        super().__init__(name="cloudflare")
        self._namespace_id: Optional[str] = None

    @staticmethod
    def typename() -> str:
        return "Cloudflare.Resources"

    @property
    def namespace_id(self) -> Optional[str]:
        return self._namespace_id

    @namespace_id.setter
    def namespace_id(self, value: str):
        self._namespace_id = value

    @staticmethod
    def initialize(res: Resources, dct: dict):
        ret = cast(CloudflareResources, res)
        super(CloudflareResources, CloudflareResources).initialize(ret, dct)
        
        if "namespace_id" in dct:
            ret._namespace_id = dct["namespace_id"]
        
        return ret

    def serialize(self) -> dict:
        out = {**super().serialize()}
        if self._namespace_id:
            out["namespace_id"] = self._namespace_id
        return out

    def update_cache(self, cache: Cache):
        super().update_cache(cache)
        if self._namespace_id:
            cache.update_config(
                val=self._namespace_id, 
                keys=["cloudflare", "resources", "namespace_id"]
            )

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Resources:
        ret = CloudflareResources()
        cached_config = cache.get_config("cloudflare")

        # Load cached values
        if cached_config and "resources" in cached_config:
            CloudflareResources.initialize(ret, cached_config["resources"])
            ret.logging_handlers = handlers
            ret.logging.info("Using cached resources for Cloudflare")
        else:
            # Check for new config
            if "resources" in config:
                CloudflareResources.initialize(ret, config["resources"])
                ret.logging_handlers = handlers
                ret.logging.info("No cached resources for Cloudflare found, using user configuration.")
            else:
                CloudflareResources.initialize(ret, {})
                ret.logging_handlers = handlers
                ret.logging.info("No resources for Cloudflare found, initialize!")

        return ret


class CloudflareConfig(Config):
    """
    Configuration for Cloudflare Workers platform.
    """
    
    def __init__(self, credentials: CloudflareCredentials, resources: CloudflareResources):
        super().__init__(name="cloudflare")
        self._credentials = credentials
        self._resources = resources

    @staticmethod
    def typename() -> str:
        return "Cloudflare.Config"

    @property
    def credentials(self) -> CloudflareCredentials:
        return self._credentials

    @property
    def resources(self) -> CloudflareResources:
        return self._resources

    @staticmethod
    def initialize(cfg: Config, dct: dict):
        config = cast(CloudflareConfig, cfg)
        # Cloudflare Workers are globally distributed, no region needed
        config._region = dct.get("region", "global")

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Config:
        cached_config = cache.get_config("cloudflare")
        credentials = cast(CloudflareCredentials, 
                          CloudflareCredentials.deserialize(config, cache, handlers))
        resources = cast(CloudflareResources, 
                        CloudflareResources.deserialize(config, cache, handlers))
        config_obj = CloudflareConfig(credentials, resources)
        config_obj.logging_handlers = handlers
        
        # Load cached values
        if cached_config:
            config_obj.logging.info("Using cached config for Cloudflare")
            CloudflareConfig.initialize(config_obj, cached_config)
        else:
            config_obj.logging.info("Using user-provided config for Cloudflare")
            CloudflareConfig.initialize(config_obj, config)

        resources.region = config_obj.region
        return config_obj

    def update_cache(self, cache: Cache):
        cache.update_config(val=self.region, keys=["cloudflare", "region"])
        self.credentials.update_cache(cache)
        self.resources.update_cache(cache)

    def serialize(self) -> dict:
        out = {
            "name": "cloudflare",
            "region": self._region,
            "credentials": self._credentials.serialize(),
            "resources": self._resources.serialize(),
        }
        return out
