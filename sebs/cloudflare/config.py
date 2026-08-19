"""Configuration classes for the Cloudflare Workers platform."""

import os
from typing import Any, Dict, Optional, Union, cast

from sebs.cache import Cache
from sebs.faas.config import Config, Credentials, Resources
from sebs.utils import LoggingHandlers


class CloudflareCredentials(Credentials):
    """
    Cloudflare API credentials.

    Two mutually exclusive authentication methods are supported; both are
    functionally equivalent for every SeBS operation (API calls, R2, KV,
    wrangler):

    - **API Token** (recommended): a scoped, revocable token created in the
      Cloudflare dashboard.  Env: ``CLOUDFLARE_API_TOKEN``.
    - **Email + Global API Key** (legacy): the account email plus the
      Global API Key.  Grants broad account access; use only when scoped
      tokens are not available.  Env: ``CLOUDFLARE_EMAIL`` +
      ``CLOUDFLARE_API_KEY``.

    Both methods additionally require ``CLOUDFLARE_ACCOUNT_ID``.

    R2 storage operations use the Cloudflare REST API with the same API token,
    so no separate S3-compatible credentials are needed.

    See ``docs/platforms.md`` (Cloudflare Workers → Credentials) for full
    setup instructions.
    """

    def __init__(
        self,
        api_token: Optional[str] = None,
        email: Optional[str] = None,
        api_key: Optional[str] = None,
        account_id: Optional[str] = None,
    ):
        """Store Cloudflare API credentials supplied at construction time."""
        super().__init__()

        self._api_token = api_token
        self._email = email
        self._api_key = api_key
        self._account_id = account_id

    @staticmethod
    def typename() -> str:
        """Return the canonical type name for this credentials class."""
        return "Cloudflare.Credentials"

    @property
    def api_token(self) -> Optional[str]:
        """Scoped API token for Cloudflare authentication."""
        return self._api_token

    @property
    def email(self) -> Optional[str]:
        """Account email used with the Global API Key authentication method."""
        return self._email

    @property
    def api_key(self) -> Optional[str]:
        """Global API Key used with the email authentication method."""
        return self._api_key

    @property
    def account_id(self) -> Optional[str]:
        """Cloudflare account ID required for all API operations."""
        return self._account_id

    @staticmethod
    def initialize(dct: dict) -> "CloudflareCredentials":
        """Build a CloudflareCredentials instance from a plain dictionary."""
        return CloudflareCredentials(
            dct.get("api_token"),
            dct.get("email"),
            dct.get("api_key"),
            dct.get("account_id"),
        )

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Credentials:
        """Load credentials from config dict, falling back to environment variables."""
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
                account_id=os.environ.get("CLOUDFLARE_ACCOUNT_ID"),
            )
        elif "CLOUDFLARE_EMAIL" in os.environ and "CLOUDFLARE_API_KEY" in os.environ:
            ret = CloudflareCredentials(
                email=os.environ["CLOUDFLARE_EMAIL"],
                api_key=os.environ["CLOUDFLARE_API_KEY"],
                account_id=os.environ.get("CLOUDFLARE_ACCOUNT_ID"),
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
        """Persist the account ID to the local cache."""
        if self._account_id:
            cache.update_config(
                val=self._account_id, keys=["cloudflare", "credentials", "account_id"]
            )

    def serialize(self) -> dict:
        """Return a serializable dict of non-secret credential fields."""
        out = {}
        if self._account_id:
            out["account_id"] = self._account_id
        return out


class CloudflareResources(Resources):
    """
    Resources for Cloudflare Workers deployment.
    """

    def __init__(self):
        """Initialize Cloudflare resources with no namespace ID assigned."""
        super().__init__(name="cloudflare")
        self._namespace_id: Optional[str] = None

    @staticmethod
    def typename() -> str:
        """Return the canonical type name for this resources class."""
        return "Cloudflare.Resources"

    @property
    def namespace_id(self) -> Optional[str]:
        """KV namespace ID associated with this resource deployment."""
        return self._namespace_id

    @namespace_id.setter
    def namespace_id(self, value: str):
        """Set the KV namespace ID for this resource deployment."""
        self._namespace_id = value

    @staticmethod
    def initialize(res: Resources, dct: dict):
        """Populate a CloudflareResources instance from a config dictionary."""
        ret = cast(CloudflareResources, res)
        super(CloudflareResources, CloudflareResources).initialize(ret, dct)

        if "namespace_id" in dct:
            ret._namespace_id = dct["namespace_id"]

        return ret

    def serialize(self) -> dict:
        """Return a serializable dict of Cloudflare resource fields."""
        out = {**super().serialize()}
        if self._namespace_id:
            out["namespace_id"] = self._namespace_id
        return out

    def update_cache(self, cache: Cache):
        """Persist resource IDs to the local cache."""
        super().update_cache(cache)
        if self._namespace_id:
            cache.update_config(
                val=self._namespace_id, keys=["cloudflare", "resources", "namespace_id"]
            )

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Resources:
        """Load resources from cached or user-provided configuration."""
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
                ret.logging.info(
                    "No cached resources for Cloudflare found, using user configuration."
                )
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
        """Initialize configuration with the given credentials and resources."""
        super().__init__(name="cloudflare")
        self._credentials = credentials
        self._resources = resources
        self._max_instances: int = 10
        self._instance_type: Optional[str] = None
        self._sleep_after: Union[str, int] = "30m"
        self._worker_placement: Dict[str, Any] = {}
        self._container_placement: Dict[str, Any] = {}
        self._r2_location_hint: Optional[str] = None
        self._r2_jurisdiction: Optional[str] = None

    @staticmethod
    def typename() -> str:
        """Return the canonical type name for this configuration class."""
        return "Cloudflare.Config"

    @property
    def credentials(self) -> CloudflareCredentials:
        """Cloudflare API credentials for this configuration."""
        return self._credentials

    @property
    def resources(self) -> CloudflareResources:
        """Cloudflare resource identifiers for this deployment."""
        return self._resources

    @property
    def max_instances(self) -> int:
        """Maximum number of container instances for container deployments."""
        return self._max_instances

    @property
    def instance_type(self) -> Optional[str]:
        """Cloudflare container instance type for container deployments."""
        return self._instance_type

    @property
    def sleep_after(self) -> Union[str, int]:
        """Idle timeout for Cloudflare container instances."""
        return self._sleep_after

    @property
    def worker_placement(self) -> Dict[str, Any]:
        """Wrangler placement configuration for native Workers."""
        return dict(self._worker_placement)

    @property
    def container_placement(self) -> Dict[str, Any]:
        """Cloudflare Container placement constraints."""
        return dict(self._container_placement)

    @property
    def r2_location_hint(self) -> Optional[str]:
        """R2 bucket location hint for newly created buckets."""
        return self._r2_location_hint

    @property
    def r2_jurisdiction(self) -> Optional[str]:
        """R2 jurisdiction for newly created buckets and Worker bindings."""
        return self._r2_jurisdiction

    @staticmethod
    def initialize(cfg: Config, dct: dict):
        """Apply region and other fields from a config dictionary to an existing instance."""
        config = cast(CloudflareConfig, cfg)
        # Cloudflare Workers are globally distributed, no region needed
        if "region" in dct:
            config._region = dct["region"]
        elif not config._region:
            config._region = "global"
        if "max_instances" in dct:
            config._max_instances = int(dct["max_instances"])
        if "instance_type" in dct:
            config._instance_type = dct["instance_type"]
        if "sleep_after" in dct:
            config._sleep_after = dct["sleep_after"]
        elif "sleepAfter" in dct:
            config._sleep_after = dct["sleepAfter"]

        placement = dct.get("placement", {}) or {}
        worker_placement = placement.get("worker", dct.get("worker_placement"))
        if worker_placement:
            config._worker_placement = dict(worker_placement)
        container_placement = placement.get("container", dct.get("container_placement"))
        if container_placement:
            config._container_placement = dict(container_placement)
        r2_placement = placement.get("r2", dct.get("r2", {})) or {}
        if "location_hint" in r2_placement:
            config._r2_location_hint = r2_placement["location_hint"]
        elif "locationHint" in r2_placement:
            config._r2_location_hint = r2_placement["locationHint"]
        if "jurisdiction" in r2_placement:
            config._r2_jurisdiction = r2_placement["jurisdiction"]

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Config:
        """Build a CloudflareConfig from user config and cache, resolving credentials."""
        cached_config = cache.get_config("cloudflare")
        credentials = cast(
            CloudflareCredentials, CloudflareCredentials.deserialize(config, cache, handlers)
        )
        resources = cast(
            CloudflareResources, CloudflareResources.deserialize(config, cache, handlers)
        )
        config_obj = CloudflareConfig(credentials, resources)
        config_obj.logging_handlers = handlers

        # Load cached values
        if cached_config:
            config_obj.logging.info("Using cached config for Cloudflare")
            CloudflareConfig.initialize(config_obj, cached_config)

        if config:
            config_obj.logging.info("Applying user-provided config for Cloudflare")
            CloudflareConfig.initialize(config_obj, config)

        resources.region = config_obj.region
        return config_obj

    def update_cache(self, cache: Cache):
        """Persist region, credentials, and resources to the local cache."""
        cache.update_config(val=self.region, keys=["cloudflare", "region"])
        cache.update_config(val=self.max_instances, keys=["cloudflare", "max_instances"])
        if self.instance_type is not None:
            cache.update_config(val=self.instance_type, keys=["cloudflare", "instance_type"])
        cache.update_config(val=self.sleep_after, keys=["cloudflare", "sleep_after"])
        if self.worker_placement:
            cache.update_config(
                val=self.worker_placement, keys=["cloudflare", "placement", "worker"]
            )
        if self.container_placement:
            cache.update_config(
                val=self.container_placement, keys=["cloudflare", "placement", "container"]
            )
        r2_placement = {}
        if self.r2_location_hint is not None:
            r2_placement["location_hint"] = self.r2_location_hint
        if self.r2_jurisdiction is not None:
            r2_placement["jurisdiction"] = self.r2_jurisdiction
        if r2_placement:
            cache.update_config(val=r2_placement, keys=["cloudflare", "placement", "r2"])
        self.credentials.update_cache(cache)
        self.resources.update_cache(cache)

    def serialize(self) -> dict:
        """Return a serializable dict of the full Cloudflare configuration."""
        out = {
            "name": "cloudflare",
            "region": self._region,
            "max_instances": self._max_instances,
            "sleep_after": self._sleep_after,
            "credentials": self._credentials.serialize(),
            "resources": self._resources.serialize(),
        }
        if self._instance_type is not None:
            out["instance_type"] = self._instance_type
        placement = {}
        if self._worker_placement:
            placement["worker"] = dict(self._worker_placement)
        if self._container_placement:
            placement["container"] = dict(self._container_placement)
        r2_placement = {}
        if self._r2_location_hint is not None:
            r2_placement["location_hint"] = self._r2_location_hint
        if self._r2_jurisdiction is not None:
            r2_placement["jurisdiction"] = self._r2_jurisdiction
        if r2_placement:
            placement["r2"] = r2_placement
        if placement:
            out["placement"] = placement
        return out
