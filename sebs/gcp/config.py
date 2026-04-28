# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
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
from __future__ import annotations

import json
import os
from typing import cast, Dict, List, Optional, Tuple
import time
from googleapiclient.errors import HttpError

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


class GCPFunctionGen1Config:
    """Configuration for Cloud Functions Gen1 deployments."""

    def __init__(self, min_instances: int = 0, max_instances: int = 20):
        """Initialize Gen1 scaling settings.

        Args:
            min_instances: Minimum number of instances to keep warm.
            max_instances: Maximum number of instances allowed.
        """
        self.min_instances = min_instances
        self.max_instances = max_instances

    def serialize(self) -> Dict:
        """Serialize the Gen1 configuration.

        Returns:
            Dictionary containing the serialized Gen1 settings.
        """
        return {"min-instances": self.min_instances, "max-instances": self.max_instances}

    @staticmethod
    def deserialize(dct: Dict) -> "GCPFunctionGen1Config":
        """Deserialize a Gen1 configuration.

        Args:
            dct: Serialized Gen1 configuration.

        Returns:
            Deserialized Gen1 configuration object.
        """
        return GCPFunctionGen1Config(
            min_instances=dct.get("min-instances", 0), max_instances=dct.get("max-instances", 20)
        )

    def __eq__(self, other: object) -> bool:
        """Compare two Gen1 configurations.

        Args:
            other: Configuration object to compare against.

        Returns:
            True if both objects have the same Gen1 settings, otherwise False.
        """
        if not isinstance(other, GCPFunctionGen1Config):
            return False
        return (
            self.min_instances == other.min_instances and self.max_instances == other.max_instances
        )


class GCPFunctionGen2Config:
    """Configuration for Cloud Functions Gen2 deployments."""

    def __init__(
        self,
        vcpus: int,
        gcp_concurrency: int,
        worker_concurrency: int,
        worker_threads: int,
        min_instances: int,
        max_instances: int,
        cpu_boost: bool,
        cpu_throttle: bool,
    ):
        """Initialize Gen2 runtime and scaling settings.

        Args:
            vcpus: Number of virtual CPUs assigned to the function.
            gcp_concurrency: Cloud Functions concurrency setting.
            worker_concurrency: Worker count used by the runtime server.
            worker_threads: Thread count used by the runtime server.
            min_instances: Minimum number of warm instances.
            max_instances: Maximum number of instances allowed.
            cpu_boost: Whether startup CPU boost is enabled.
            cpu_throttle: Whether CPU throttling is enabled when idle.
        """
        self.vcpus = vcpus
        self.gcp_concurrency = gcp_concurrency
        self.worker_concurrency = worker_concurrency
        self.worker_threads = worker_threads
        self.min_instances = min_instances
        self.max_instances = max_instances
        self.cpu_boost = cpu_boost
        self.cpu_throttle = cpu_throttle

    def serialize(self) -> Dict:
        """Serialize the Gen2 configuration.

        Returns:
            Dictionary containing the serialized Gen2 settings.
        """
        return {
            "vcpus": self.vcpus,
            "gcp-concurrency": self.gcp_concurrency,
            "worker-concurrency": self.worker_concurrency,
            "worker-threads": self.worker_threads,
            "min-instances": self.min_instances,
            "max-instances": self.max_instances,
            "cpu-boost": self.cpu_boost,
            "cpu-throttle": self.cpu_throttle,
        }

    @staticmethod
    def deserialize(dct: Dict) -> GCPFunctionGen2Config:
        """Deserialize a Gen2 configuration.

        Args:
            dct: Serialized Gen2 configuration.

        Returns:
            Deserialized Gen2 configuration object.
        """
        return GCPFunctionGen2Config(
            vcpus=dct["vcpus"],
            gcp_concurrency=dct["gcp-concurrency"],
            worker_concurrency=dct["worker-concurrency"],
            worker_threads=dct["worker-threads"],
            min_instances=dct["min-instances"],
            max_instances=dct["max-instances"],
            cpu_boost=dct["cpu-boost"],
            cpu_throttle=dct["cpu-throttle"],
        )

    def __eq__(self, other: object) -> bool:
        """Compare two Gen2 configurations.

        Args:
            other: Configuration object to compare against.

        Returns:
            True if both objects have the same Gen2 settings, otherwise False.
        """
        if not isinstance(other, GCPFunctionGen2Config):
            return False
        return (
            self.vcpus == other.vcpus
            and self.gcp_concurrency == other.gcp_concurrency
            and self.worker_concurrency == other.worker_concurrency
            and self.worker_threads == other.worker_threads
            and self.min_instances == other.min_instances
            and self.max_instances == other.max_instances
            and self.cpu_boost == other.cpu_boost
            and self.cpu_throttle == other.cpu_throttle
        )


class GCPContainerConfig(GCPFunctionGen2Config):
    """Configuration for Cloud Run container deployments."""

    def __init__(
        self,
        environment: str,
        vcpus: int,
        gcp_concurrency: int,
        worker_concurrency: int,
        worker_threads: int,
        min_instances: int,
        max_instances: int,
        cpu_boost: bool,
        cpu_throttle: bool,
    ):
        """Initialize Cloud Run container settings.

        Args:
            environment: Cloud Run execution environment name.
            vcpus: Number of virtual CPUs assigned to the container.
            gcp_concurrency: Cloud Run request concurrency limit.
            worker_concurrency: Worker count used by the runtime server.
            worker_threads: Thread count used by the runtime server.
            min_instances: Minimum number of warm instances.
            max_instances: Maximum number of instances allowed.
            cpu_boost: Whether startup CPU boost is enabled.
            cpu_throttle: Whether CPU throttling is enabled when idle.
        """
        super().__init__(
            vcpus,
            gcp_concurrency,
            worker_concurrency,
            worker_threads,
            min_instances,
            max_instances,
            cpu_boost,
            cpu_throttle,
        )
        self.environment = environment

    def serialize(self) -> Dict:
        """Serialize the container configuration.

        Returns:
            Dictionary containing the serialized container settings.
        """
        return {**super().serialize(), "environment": self.environment}

    @staticmethod
    def deserialize(dct: Dict) -> GCPContainerConfig:
        """Deserialize a container configuration.

        Args:
            dct: Serialized container configuration.

        Returns:
            Deserialized container configuration object.
        """
        return GCPContainerConfig(
            environment=dct["environment"],
            vcpus=dct["vcpus"],
            gcp_concurrency=dct["gcp-concurrency"],
            worker_concurrency=dct["worker-concurrency"],
            worker_threads=dct["worker-threads"],
            min_instances=dct["min-instances"],
            max_instances=dct["max-instances"],
            cpu_boost=dct["cpu-boost"],
            cpu_throttle=dct["cpu-throttle"],
        )

    def __eq__(self, other: object) -> bool:
        """Compare two container configurations.

        Args:
            other: Configuration object to compare against.

        Returns:
            True if both objects have the same container settings, otherwise False.
        """
        if not isinstance(other, GCPContainerConfig):
            return False
        return (
            self.environment == other.environment
            and self.vcpus == other.vcpus
            and self.gcp_concurrency == other.gcp_concurrency
            and self.worker_concurrency == other.worker_concurrency
            and self.worker_threads == other.worker_threads
            and self.min_instances == other.min_instances
            and self.max_instances == other.max_instances
            and self.cpu_boost == other.cpu_boost
            and self.cpu_throttle == other.cpu_throttle
        )


class GCPConfiguration:
    """User-provided configuration of workloads on the GCP.

    Currently, this class primarily inherits functionality from the base `Resources`
    class, as we do not need more GCP-specific resources beyond standard storage buckets.

    Attributes:
        Inherits all attributes from the base Resources class
    """

    def __init__(self) -> None:
        """Initialize default GCP deployment configuration."""
        self._function_gen1_config: GCPFunctionGen1Config
        self._function_gen2_config: GCPFunctionGen2Config
        self._container_config: GCPContainerConfig
        self._package_deployment_type: str = "function-gen1"

    @staticmethod
    def initialize(config: GCPConfiguration, dct: Dict) -> GCPConfiguration:
        """Populate a configuration object from serialized data.

        Args:
            config: Configuration object to populate.
            dct: Serialized deployment configuration.

        Returns:
            The populated configuration object.
        """

        config._function_gen1_config = GCPFunctionGen1Config.deserialize(dct["function-gen1"])
        config._function_gen2_config = GCPFunctionGen2Config.deserialize(dct["function-gen2"])
        config._container_config = GCPContainerConfig.deserialize(dct["container"])
        config._package_deployment_type = dct.get("package-deployment-type", "function-gen1")

        if config._package_deployment_type not in ("function-gen1", "function-gen2"):
            raise ValueError(
                "Invalid GCP package deployment type "
                f"{config._package_deployment_type}. Expected function-gen1 or function-gen2."
            )

        return config

    def serialize(self) -> Dict:
        """Serialize resources to dictionary for cache storage.

        Returns:
            Dictionary representation of resources for cache storage
        """
        out = {}
        out["function-gen1"] = self._function_gen1_config.serialize()
        out["function-gen2"] = self._function_gen2_config.serialize()
        out["container"] = self._container_config.serialize()
        out["package-deployment-type"] = self._package_deployment_type
        return out

    @property
    def function_gen1_config(self) -> GCPFunctionGen1Config:
        """Get the Gen1 deployment configuration.

        Returns:
            Gen1 deployment configuration object.
        """
        return self._function_gen1_config

    @property
    def function_gen2_config(self) -> GCPFunctionGen2Config:
        """Get the Gen2 deployment configuration.

        Returns:
            Gen2 deployment configuration object.
        """
        return self._function_gen2_config

    @property
    def container_config(self) -> GCPContainerConfig:
        """Get the Cloud Run container configuration.

        Returns:
            Cloud Run container deployment configuration object.
        """
        return self._container_config

    @property
    def package_deployment_type(self) -> str:
        """Get the package deployment selector used when container mode is disabled."""
        return self._package_deployment_type


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
        self._container_repository: Optional[str] = None

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
        out = super().serialize()
        out["container_repository"] = self._container_repository
        return out

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

    @property
    def container_repository(self) -> str:
        """Get the Artifact Registry repository name for containers."""
        assert self._container_repository is not None, "Container repository has not been set yet!"
        return self._container_repository

    def check_container_repository_exists(self, config: Config, ar_client):
        """Check whether the configured container repository exists."""
        try:
            credentials = cast(GCPCredentials, config.credentials)
            parent = f"projects/{credentials.project_name}/locations/{config.region}"
            repo_full_name = f"{parent}/repositories/{self._container_repository}"
            self.logging.info("Checking if container repository exists...")
            ar_client.projects().locations().repositories().get(name=repo_full_name).execute()
            return True
        except HttpError as e:
            if e.resp.status == 404:
                self.logging.info("Container repository does not exist.")
                return False
            else:
                raise e

    def create_container_repository(self, ar_client, parent):
        """Create the Artifact Registry repository for benchmark containers."""
        request_body = {"format": "DOCKER", "description": "Container repository for SEBS"}
        self._container_repository = f"sebs-benchmarks-{self._resources_id}"
        operation = (
            ar_client.projects()
            .locations()
            .repositories()
            .create(parent=parent, body=request_body, repositoryId=self._container_repository)
            .execute()
        )

        attempt = 0
        max_retries = 10

        while attempt < max_retries:
            # Operations for AR are global or location specific
            op_name = operation["name"]
            op = ar_client.projects().locations().operations().get(name=op_name).execute()

            if op.get("done"):
                if "error" in op:
                    raise Exception(f"Failed to create repo: {op['error']}")
                self.logging.info("Repository created successfully.")
                break
            time.sleep(2)
            attempt += 1

        if attempt == max_retries:
            raise TimeoutError("Timed out waiting for container repository creation.")

    def get_container_repository(self, config: Config, ar_client):
        """Get or create the Artifact Registry repository for container images."""
        if self._container_repository is not None:
            return self._container_repository

        self._container_repository = f"sebs-benchmarks-{self._resources_id}"
        if self.check_container_repository_exists(config, ar_client):
            return self._container_repository

        credentials = cast(GCPCredentials, config.credentials)
        parent = f"projects/{credentials.project_name}/locations/{config.region}"
        self.create_container_repository(ar_client, parent)
        return self._container_repository


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

        self._deployment_config = GCPConfiguration()

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

    @property
    def deployment_config(self) -> GCPConfiguration:
        """Get the deployment configuration for GCP workloads.

        Returns:
            GCPConfiguration instance containing workload deployment settings
        """
        return self._deployment_config

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

        # deployment configuration is never loaded from cache - always fresh!
        if "configuration" in config:
            GCPConfiguration.initialize(config_obj.deployment_config, config["configuration"])

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
