import json
import os
from typing import cast, List, Optional, Tuple

from sebs.cache import Cache
from sebs.faas.config import Config, Credentials, Resources
from sebs.utils import LoggingHandlers

# FIXME: Replace type hints for static generators after migration to 3.7
# https://stackoverflow.com/questions/33533148/how-do-i-specify-that-the-return-type-of-a-method-is-the-same-as-the-class-itsel

"""
Configuration classes for Google Cloud Platform (GCP) FaaS deployments.

This module defines how GCP credentials, resources (like Cloud Storage buckets),
and general deployment settings are managed within SeBS.
"""


class GCPCredentials(Credentials):
    """
    GCP service account credentials.

    The order of credentials initialization:
    1. Load credentials from cache.
    2. If new values are provided in the config (path to JSON), they override cache values.
    3. If nothing is provided, initialize using `GOOGLE_APPLICATION_CREDENTIALS` environment variable.
    4. Fallback to `GCP_SECRET_APPLICATION_CREDENTIALS` environment variable.
    5. If no information is provided, then failure is reported.
    """
    def __init__(self, gcp_credentials_path: str):
        """
        Initialize GCP credentials.

        :param gcp_credentials_path: Path to the GCP service account JSON credentials file.
        """
        super().__init__()
        self._gcp_credentials = gcp_credentials_path
        with open(self._gcp_credentials, "r") as f:
            gcp_data = json.load(f)
        self._project_id = gcp_data["project_id"]

    @property
    def gcp_credentials(self) -> str:
        """Path to the GCP service account JSON credentials file."""
        return self._gcp_credentials

    @property
    def project_name(self) -> str:
        """Google Cloud project ID extracted from the credentials file."""
        return self._project_id

    @staticmethod
    def initialize(gcp_credentials_path: str) -> "GCPCredentials":
        """
        Initialize GCPCredentials from a given path to the credentials JSON file.

        :param gcp_credentials_path: Path to the GCP service account JSON file.
        :return: GCPCredentials instance.
        """
        return GCPCredentials(gcp_credentials_path)

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Credentials:
        """
        Deserialize GCP credentials from configuration, cache, or environment variables.

        Sets `GOOGLE_APPLICATION_CREDENTIALS` environment variable if credentials
        are loaded from SeBS config or SeBS-specific environment variables.

        :param config: Configuration dictionary.
        :param cache: Cache object.
        :param handlers: Logging handlers.
        :return: GCPCredentials instance.
        :raises RuntimeError: If credentials are not found or if project ID mismatch with cache.
        """
        cached_config = cache.get_config("gcp")
        ret: GCPCredentials
        cached_project_id: Optional[str] = None

        if cached_config and "credentials" in cached_config:
            cached_project_id = cached_config["credentials"].get("project_id")

        creds_path_from_config = config.get("credentials", {}).get("credentials-json")
        env_gac = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        env_sebs_gac = os.environ.get("GCP_SECRET_APPLICATION_CREDENTIALS")

        if creds_path_from_config:
            ret = GCPCredentials.initialize(creds_path_from_config)
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = ret.gcp_credentials
        elif env_gac:
            ret = GCPCredentials(env_gac)
        elif env_sebs_gac:
            ret = GCPCredentials(env_sebs_gac)
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = ret.gcp_credentials
        else:
            raise RuntimeError(
                "GCP login credentials are missing! Please set the path to .json "
                "with cloud credentials in config ('credentials-json') or in the "
                "GOOGLE_APPLICATION_CREDENTIALS or GCP_SECRET_APPLICATION_CREDENTIALS "
                "environmental variable."
            )
        ret.logging_handlers = handlers

        if cached_project_id is not None and cached_project_id != ret.project_name:
            ret.logging.error(
                f"The project id {ret.project_name} from provided "
                f"credentials is different from the ID {cached_project_id} in the cache! "
                "Please change your cache directory or create a new one!"
            )
            raise RuntimeError(
                f"GCP login credentials do not match the project {cached_project_id} in cache!"
            )
        return ret

    def serialize(self) -> dict:
        """
        Serialize GCP credentials to a dictionary for storage in cache.

        Only stores the project_id, as the path to credentials might change or be
        environment-dependent. The actual credential path is expected to be resolved
        during deserialization.

        :return: Dictionary containing the project ID.
        """
        out = {"project_id": self._project_id}
        return out

    def update_cache(self, cache: Cache):
        """
        Update the cache with the GCP project ID.

        :param cache: Cache object.
        """
        cache.update_config(val=self._project_id, keys=["gcp", "credentials", "project_id"])


class GCPResources(Resources):
    """
    Manages GCP resources allocated for SeBS.

    Currently, this class primarily inherits functionality from the base `Resources`
    class, as GCP-specific resources beyond standard storage buckets (handled by base)
    are not explicitly managed here yet (e.g., specific IAM roles if needed beyond
    service account permissions, or API Gateway configurations).
    """
    def __init__(self):
        """Initialize GCPResources."""
        super().__init__(name="gcp")

    @staticmethod
    def initialize(res: Resources, dct: dict):
        """
        Initialize GCPResources from a dictionary.

        Calls the parent class's initialize method.

        :param res: Resources object to initialize (cast to GCPResources).
        :param dct: Dictionary containing resource configurations.
        :return: Initialized GCPResources instance.
        """
        ret = cast(GCPResources, res)
        super(GCPResources, GCPResources).initialize(ret, dct)
        # GCP-specific resource initialization can be added here if needed.
        return ret

    def serialize(self) -> dict:
        """
        Serialize GCPResources to a dictionary for storage in cache.

        Calls the parent class's serialize method.

        :return: Dictionary representation of GCPResources.
        """
        return super().serialize()

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> "Resources":
        """
        Deserialize GCPResources from configuration or cache.

        Prioritizes cached configuration if available.

        :param config: Configuration dictionary.
        :param cache: Cache object.
        :param handlers: Logging handlers.
        :return: GCPResources instance.
        """
        cached_config = cache.get_config("gcp")
        ret = GCPResources()
        if cached_config and "resources" in cached_config:
            GCPResources.initialize(ret, cached_config["resources"])
            ret.logging_handlers = handlers
            ret.logging.info("Using cached resources for GCP")
        else:
            if "resources" in config:
                GCPResources.initialize(ret, config["resources"])
                ret.logging_handlers = handlers
                ret.logging.info("No cached resources for GCP found, using user configuration.")
            else:
                # Initialize with empty dict if no specific resources config is provided
                GCPResources.initialize(ret, {})
                ret.logging_handlers = handlers
                ret.logging.info("No resources for GCP found, initialize!")
        return ret

    def update_cache(self, cache: Cache):
        """
        Update the cache with GCP resource details.

        Calls the parent class's update_cache method.

        :param cache: Cache object.
        """
        super().update_cache(cache)


class GCPConfig(Config):
    """GCP specific configuration, including credentials, resources, and project name."""
    _project_name: str # While project_name is a property, this might be for internal use or type hinting

    def __init__(self, credentials: GCPCredentials, resources: GCPResources):
        """
        Initialize GCPConfig.

        :param credentials: GCPCredentials instance.
        :param resources: GCPResources instance.
        """
        super().__init__(name="gcp")
        self._credentials = credentials
        self._resources = resources
        # self._project_name = credentials.project_name # Initialize if needed, though property accesses it

    @property
    def region(self) -> str:
        """The GCP region for the deployment (e.g., "us-central1")."""
        return self._region

    @property
    def project_name(self) -> str:
        """The Google Cloud project ID/name."""
        return self.credentials.project_name

    @property
    def credentials(self) -> GCPCredentials:
        """Return the GCP credentials."""
        return self._credentials

    @property
    def resources(self) -> GCPResources:
        """Return the GCP resources configuration."""
        return self._resources

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> "Config":
        """
        Deserialize GCPConfig from configuration or cache.

        Deserializes credentials and resources, then initializes the GCPConfig
        object, prioritizing cached configuration. It also handles updates to
        cached values if the user provides different ones in the input configuration.

        :param config: Configuration dictionary.
        :param cache: Cache object.
        :param handlers: Logging handlers.
        :return: GCPConfig instance.
        """
        cached_config = cache.get_config("gcp")
        credentials = cast(GCPCredentials, GCPCredentials.deserialize(config, cache, handlers))
        resources = cast(GCPResources, GCPResources.deserialize(config, cache, handlers))
        config_obj = GCPConfig(credentials, resources)
        config_obj.logging_handlers = handlers

        if cached_config:
            config_obj.logging.info("Loading cached config for GCP")
            GCPConfig.initialize(config_obj, cached_config) # Initialize with cached values first
        else:
            config_obj.logging.info("Using user-provided config for GCP as no cache found")
            GCPConfig.initialize(config_obj, config) # Initialize with user config

        # Update cached values if user provided different ones, only for specific keys like region
        # The original logic for updated_keys seems specific and might need review for generality.
        # Assuming 'region' is the primary updatable field here from user config over cache.
        user_provided_region = config.get("region")
        if user_provided_region and config_obj.region != user_provided_region:
            config_obj.logging.info(
                f"Updating cached region {config_obj.region} "
                f"to user-provided value {user_provided_region}."
            )
            config_obj._region = user_provided_region # Directly update the backing field
            # The cache update for region is handled by the main update_cache method.

        # Ensure resources have the correct region set, especially if config_obj.region changed
        config_obj.resources.region = config_obj.region
        return config_obj

    @staticmethod
    def initialize(cfg: Config, dct: dict):
        """
        Initialize GCPConfig attributes from a dictionary.

        Sets the GCP region.

        :param cfg: Config object to initialize (cast to GCPConfig).
        :param dct: Dictionary containing 'region'.
        """
        config = cast(GCPConfig, cfg)
        config._region = dct["region"]
        # Ensure resources also get the region if being initialized here
        if hasattr(config, '_resources') and config._resources:
            config._resources.region = dct["region"]


    def serialize(self) -> dict:
        """
        Serialize GCPConfig to a dictionary.

        Includes region, credentials, and resources.

        :return: Dictionary representation of GCPConfig.
        """
        out = {
            "name": "gcp",
            "region": self._region,
            "credentials": self._credentials.serialize(),
            "resources": self._resources.serialize(),
        }
        return out

    def update_cache(self, cache: Cache):
        """
        Update the user cache with GCP configuration.

        Saves region, credentials (project_id), and resources to the cache.

        :param cache: Cache object.
        """
        cache.update_config(val=self.region, keys=["gcp", "region"])
        self.credentials.update_cache(cache)
        self.resources.update_cache(cache)
