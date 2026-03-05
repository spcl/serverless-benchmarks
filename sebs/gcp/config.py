"""Configuration classes for Google Cloud Platform (GCP) integration.

This module provides configuration classes for GCP,
including credentials management, resource allocation, and cloud region configuration.
It handles authentication through service account JSON files and manages project-specific
settings required for Cloud Functions deployment and execution.

Classes:
    GCPCredentials: Handles authentication and project identification
    GCPResources: Manages allocated cloud resources
    GCPConfig: Main configuration container for GCP deployment

Example:
    Basic GCP configuration setup:

        credentials = GCPCredentials("/path/to/service-account.json")
        resources = GCPResources()
        config = GCPConfig(credentials, resources)
"""

import json
import os
from typing import cast, Dict, List, Optional, Tuple

from sebs.cache import Cache
from sebs.faas.config import Config, Credentials, Resources
from sebs.utils import LoggingHandlers


class GCPCredentials(Credentials):
    """Credentials manager for Google Cloud Platform authentication.

    Handles authentication to GCP services using service account JSON files.
    Automatically extracts project ID from credentials and manages environment
    variable setup for Google Cloud SDK authentication.

    The class supports multiple credential sources in priority order:
    1. User-provided credentials file path
    2. GOOGLE_APPLICATION_CREDENTIALS environment variable
    3. GCP_SECRET_APPLICATION_CREDENTIALS environment variable

    Attributes:
        _gcp_credentials: Path to the service account JSON file
        _project_id: GCP project ID extracted from credentials
    """

    def __init__(self, gcp_credentials: str) -> None:
        """Initialize GCP credentials with service account file.

        Args:
            gcp_credentials: Path to the GCP service account JSON file

        Raises:
            FileNotFoundError: If the credentials file doesn't exist
            json.JSONDecodeError: If the credentials file is not valid JSON
            KeyError: If the credentials file doesn't contain project_id
        """
        super().__init__()

        self._gcp_credentials = gcp_credentials

        gcp_data = json.load(open(self._gcp_credentials, "r"))
        self._project_id = gcp_data["project_id"]

    @property
    def gcp_credentials(self) -> str:
        """Get the path to the GCP service account credentials file.

        Returns:
            Path to the service account JSON file
        """
        return self._gcp_credentials

    @property
    def project_name(self) -> str:
        """Get the GCP project ID from the credentials.

        Returns:
            The GCP project ID string
        """
        return self._project_id

    @staticmethod
    def initialize(gcp_credentials: str) -> "GCPCredentials":
        """Create a new GCPCredentials instance.

        Args:
            gcp_credentials: Path to the GCP service account JSON file

        Returns:
            A new GCPCredentials instance
        """
        return GCPCredentials(gcp_credentials)

    @staticmethod
    def deserialize(config: Dict, cache: Cache, handlers: LoggingHandlers) -> Credentials:
        """Deserialize GCP credentials from configuration and cache.

        Loads credentials from multiple sources in priority order:
        1. User-provided config with credentials-json path
        2. GOOGLE_APPLICATION_CREDENTIALS environment variable
        3. GCP_SECRET_APPLICATION_CREDENTIALS environment variable

        Sets the `GOOGLE_APPLICATION_CREDENTIALS` environment variable if credentials
        are loaded from SeBS config or SeBS-specific environment variables.

        Args:
            config: Configuration dictionary potentially containing credentials
            cache: Cache instance for storing/retrieving credentials
            handlers: Logging handlers for error reporting

        Returns:
            Initialized GCPCredentials instance

        Raises:
            RuntimeError: If no valid credentials are found or if project ID
                         mismatch occurs between cache and new credentials
        """

        cached_config = cache.get_config("gcp")
        ret: GCPCredentials
        project_id: Optional[str] = None

        # Load cached values
        if cached_config and "credentials" in cached_config:
            project_id = cached_config["credentials"]["project_id"]

        # Check for new config
        if "credentials" in config and "credentials-json" in config["credentials"]:
            ret = GCPCredentials.initialize(config["credentials"]["credentials-json"])
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = ret.gcp_credentials
        # Look for default GCP credentials
        elif "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
            ret = GCPCredentials(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
        # Look for our environment variables
        elif "GCP_SECRET_APPLICATION_CREDENTIALS" in os.environ:
            ret = GCPCredentials(os.environ["GCP_SECRET_APPLICATION_CREDENTIALS"])
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = ret.gcp_credentials
        else:
            raise RuntimeError(
                "GCP login credentials are missing! Please set the path to .json "
                "with cloud credentials in config or in the GCP_SECRET_APPLICATION_CREDENTIALS "
                "environmental variable"
            )
        ret.logging_handlers = handlers

        if project_id is not None and project_id != ret._project_id:
            ret.logging.error(
                f"The project id {ret._project_id} from provided "
                f"credentials is different from the ID {project_id} in the cache! "
                "Please change your cache directory or create a new one!"
            )
            raise RuntimeError(
                f"GCP login credentials do not match the project {project_id} in cache!"
            )

        return ret

    def serialize(self) -> Dict:
        """Serialize credentials to dictionary for cache storage.

        Only stores the project_id, as the path to credentials might change or be
        environment-dependent. It also avoids any potential security issues.

        Returns:
            Dictionary containing project_id for cache storage
        """
        out = {"project_id": self._project_id}
        return out

    def update_cache(self, cache: Cache) -> None:
        """Update the cache with current GCP project id.

        Args:
            cache: Cache instance to update with project ID
        """
        cache.update_config(val=self._project_id, keys=["gcp", "credentials", "project_id"])


class GCPResources(Resources):
    """Resource manager for serverless resources on Google Cloud Platform.

    Currently, this class primarily inherits functionality from the base `Resources`
    class, as we do not need more GCP-specific resources beyond standard storage buckets.

    Attributes:
        Inherits all attributes from the base Resources class
    """

    def __init__(self) -> None:
        """Initialize GCP resources manager."""
        super().__init__(name="gcp")

    @staticmethod
    def initialize(res: Resources, dct: Dict) -> "GCPResources":
        """Initialize GCP resources from a dictionary configuration.

        Args:
            res: Base Resources instance to initialize
            dct: Dictionary containing resource configuration

        Returns:
            Initialized GCPResources instance
        """
        ret = cast(GCPResources, res)
        super(GCPResources, GCPResources).initialize(ret, dct)
        return ret

    def serialize(self) -> Dict:
        """Serialize resources to dictionary for cache storage.

        Returns:
            Dictionary representation of resources for cache storage
        """
        return super().serialize()

    @staticmethod
    def deserialize(config: Dict, cache: Cache, handlers: LoggingHandlers) -> "Resources":
        """Deserialize GCP resources from configuration and cache.

        Loads resources from cache if available, otherwise initializes from
        user configuration or creates empty resource set.

        Args:
            config: Configuration dictionary potentially containing resources
            cache: Cache instance for storing/retrieving resources
            handlers: Logging handlers for status reporting

        Returns:
            Initialized GCPResources instance
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
                GCPResources.initialize(ret, {})
                ret.logging_handlers = handlers
                ret.logging.info("No resources for GCP found, initialize!")

        return ret

    def update_cache(self, cache: Cache) -> None:
        """Update the cache with current resource information.

        Args:
            cache: Cache instance to update with resource data
        """
        super().update_cache(cache)


class GCPConfig(Config):
    """Main configuration class for Google Cloud Platform deployment.

    Combines credentials and resources into a complete configuration for
    GCP serverless function deployment. Manages cloud region settings,
    authentication, and resource allocation for the benchmarking suite.

    This class handles serialization/deserialization for cache persistence
    and provides validation for configuration consistency across sessions.

    Attributes:
        _project_name: GCP project identifier
        _region: GCP region for resource deployment
        _credentials: GCP authentication credentials
        _resources: Allocated GCP resources
    """

    _project_name: str

    def __init__(self, credentials: GCPCredentials, resources: GCPResources) -> None:
        """Initialize GCP configuration with credentials and resources.

        Args:
            credentials: GCP authentication credentials
            resources: GCP resource allocation settings
        """
        super().__init__(name="gcp")
        self._credentials = credentials
        self._resources = resources

    @property
    def region(self) -> str:
        """Get the GCP region for resource deployment.

        Returns:
            GCP region identifier (e.g., 'us-central1')
        """
        return self._region

    @property
    def project_name(self) -> str:
        """Get the GCP project name from credentials.

        Returns:
            GCP project identifier string
        """
        return self.credentials.project_name

    @property
    def credentials(self) -> GCPCredentials:
        """Get the GCP credentials instance.

        Returns:
            GCP authentication credentials
        """
        return self._credentials

    @property
    def resources(self) -> GCPResources:
        """Get the GCP resources instance.

        Returns:
            GCP resource allocation settings
        """
        return self._resources

    @staticmethod
    def deserialize(config: Dict, cache: Cache, handlers: LoggingHandlers) -> "Config":
        """Deserialize GCP configuration from dictionary and cache.

        Loads complete GCP configuration including credentials and resources.
        Validates consistency between cached and provided configuration values,
        updating cache with new user-provided values when they differ.

        Args:
            config: Configuration dictionary with GCP settings
            cache: Cache instance for storing/retrieving configuration
            handlers: Logging handlers for status reporting

        Returns:
            Initialized GCPConfig instance
        """
        cached_config = cache.get_config("gcp")
        credentials = cast(GCPCredentials, GCPCredentials.deserialize(config, cache, handlers))
        resources = cast(GCPResources, GCPResources.deserialize(config, cache, handlers))
        config_obj = GCPConfig(credentials, resources)
        config_obj.logging_handlers = handlers

        if cached_config:
            config_obj.logging.info("Loading cached config for GCP")
            GCPConfig.initialize(config_obj, cached_config)
        else:
            config_obj.logging.info("Using user-provided config for GCP")
            GCPConfig.initialize(config_obj, config)

        # mypy makes a mistake here
        updated_keys: List[Tuple[str, List[str]]] = [("region", ["gcp", "region"])]  # type: ignore
        # for each attribute here, check if its version is different than the one provided by
        # user; if yes, then update the value
        for config_key, keys in updated_keys:

            old_value = getattr(config_obj, config_key)
            # ignore empty values
            if getattr(config_obj, config_key) != config[config_key] and config[config_key]:
                config_obj.logging.info(
                    f"Updating cached key {config_key} with {old_value} "
                    f"to user-provided value {config[config_key]}."
                )
                setattr(config_obj, f"_{config_key}", config[config_key])
                cache.update_config(val=getattr(config_obj, config_key), keys=keys)

        return config_obj

    @staticmethod
    def initialize(cfg: Config, dct: Dict) -> None:
        """Initialize GCP configuration from dictionary.

        Args:
            cfg: Config instance to initialize (will be cast to GCPConfig)
            dct: Dictionary containing configuration values including region
        """
        config = cast(GCPConfig, cfg)
        config._region = dct["region"]

    def serialize(self) -> Dict:
        """Serialize configuration to dictionary for cache storage.

        Returns:
            Dictionary containing complete GCP configuration including
            name, region, credentials, and resources
        """
        out = {
            "name": "gcp",
            "region": self._region,
            "credentials": self._credentials.serialize(),
            "resources": self._resources.serialize(),
        }
        return out

    def update_cache(self, cache: Cache) -> None:
        """Update cache with current configuration values.

        Updates region, credentials, and resources in the cache.

        Args:
            cache: Cache instance to update with configuration data
        """
        cache.update_config(val=self.region, keys=["gcp", "region"])
        self.credentials.update_cache(cache)
        self.resources.update_cache(cache)
