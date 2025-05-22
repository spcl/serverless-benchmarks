import os
from typing import Optional, Dict, Type

import docker

from sebs import types
from sebs.local import Local
from sebs.cache import Cache
from sebs.config import SeBSConfig
from sebs.benchmark import Benchmark
from sebs.faas.system import System as FaaSSystem
from sebs.faas.storage import PersistentStorage
from sebs.faas.nosql import NoSQLStorage
from sebs.faas.config import Config
from sebs.storage import minio, config, scylladb
from sebs.utils import has_platform, LoggingHandlers, LoggingBase

from sebs.experiments.config import Config as ExperimentConfig
from sebs.experiments import Experiment


class SeBS(LoggingBase):
    """
    The main SeBS client class.

    This class orchestrates benchmark execution, FaaS deployment interactions,
    experiment management, and result processing. It initializes and holds
    clients for Docker, caching, and system-wide configurations.
    """
    @property
    def cache_client(self) -> Cache:
        """The SeBS cache client instance."""
        return self._cache_client

    @property
    def docker_client(self) -> docker.client.DockerClient: # More specific type
        """The Docker client instance."""
        return self._docker_client

    @property
    def output_dir(self) -> str:
        """The base directory for SeBS outputs and results."""
        return self._output_dir

    @property
    def verbose(self) -> bool:
        """Flag indicating if verbose logging is enabled."""
        return self._verbose

    @property
    def logging_filename(self) -> Optional[str]:
        """The filename for logging, if configured."""
        return self._logging_filename

    @property
    def config(self) -> SeBSConfig:
        """The global SeBS system configuration instance."""
        return self._config

    def generate_logging_handlers(self, logging_filename: Optional[str] = None) -> LoggingHandlers:
        """
        Generate or retrieve logging handlers for a given filename.

        Caches handlers by filename to avoid redundant creation.

        :param logging_filename: Optional filename for the log. If None, uses the default.
        :return: LoggingHandlers instance.
        """
        filename_key = logging_filename if logging_filename else self.logging_filename
        # Use a different key for None to avoid issues if filename could be ""
        # For simplicity, assuming logging_filename being None means default log.
        if filename_key in self._handlers:
            return self._handlers[filename_key]
        else:
            handlers = LoggingHandlers(verbose=self.verbose, filename=filename_key)
            self._handlers[filename_key] = handlers
            return handlers

    def __init__(
        self,
        cache_dir: str,
        output_dir: str,
        verbose: bool = False,
        logging_filename: Optional[str] = None,
    ):
        """
        Initialize the SeBS client.

        Sets up Docker client, cache client, system configuration, output directory,
        and logging handlers.

        :param cache_dir: Path to the directory for SeBS cache.
        :param output_dir: Path to the base directory for SeBS outputs.
        :param verbose: Enable verbose logging if True.
        :param logging_filename: Optional filename for logging output.
        """
        super().__init__()
        self._docker_client: docker.client.DockerClient = docker.from_env()
        self._cache_client = Cache(cache_dir, self._docker_client)
        self._config = SeBSConfig()
        self._output_dir = os.path.abspath(output_dir) # Ensure absolute path
        self._verbose = verbose
        self._logging_filename = logging_filename
        self._handlers: Dict[Optional[str], LoggingHandlers] = {} # Cache for logging handlers
        self.logging_handlers = self.generate_logging_handlers() # Initialize default handlers

        os.makedirs(self.output_dir, exist_ok=True)

    def ignore_cache(self):
        """
        Configure the cache client to ignore (not update) function and storage details.
        Code packages might still be stored or updated based on internal cache logic.
        """
        self._cache_client.ignore_storage = True
        self._cache_client.ignore_functions = True

    def get_deployment(
        self,
        user_config: dict, # Renamed from config for clarity
        logging_filename: Optional[str] = None,
        # Allow passing an already deserialized deployment_config to avoid re-parsing
        deployment_faas_config: Optional[Config] = None, # Renamed
    ) -> FaaSSystem:
        """
        Get and initialize a FaaS deployment client based on the provided configuration.

        Dynamically loads the appropriate FaaS system implementation (e.g., AWS, Azure)
        and initializes it with configurations.

        :param user_config: Dictionary containing user-provided configuration,
                            expected to have a "deployment" key for FaaS system details
                            and an "experiments" key for experiment-related settings.
        :param logging_filename: Optional filename for logs specific to this deployment.
        :param deployment_faas_config: Optional pre-deserialized FaaS Config object.
        :return: An initialized FaaSSystem instance for the specified provider.
        :raises RuntimeError: If the deployment name is not supported or if configuration is invalid.
        """
        deployment_settings = user_config["deployment"]
        deployment_name = deployment_settings["name"]
        
        # Map deployment names to their respective System classes
        faas_implementations: Dict[str, Type[FaaSSystem]] = {"local": Local}
        if has_platform("aws"):
            from sebs.aws import AWS
            faas_implementations["aws"] = AWS
        if has_platform("azure"):
            from sebs.azure.azure import Azure
            faas_implementations["azure"] = Azure
        if has_platform("gcp"):
            from sebs.gcp import GCP
            faas_implementations["gcp"] = GCP
        if has_platform("openwhisk"):
            from sebs.openwhisk import OpenWhisk
            faas_implementations["openwhisk"] = OpenWhisk

        if deployment_name not in faas_implementations:
            raise RuntimeError(f"Deployment {deployment_name} not supported!")

        exp_config_dict = user_config.get("experiments", {})
        target_architecture = exp_config_dict.get("architecture")
        is_container_deployment = exp_config_dict.get("container_deployment", False)

        if not target_architecture or target_architecture not in self._config.supported_architecture(deployment_name):
            raise RuntimeError(f"Architecture {target_architecture} is not supported in {deployment_name}")

        if is_container_deployment and not self._config.supported_container_deployment(deployment_name):
            raise RuntimeError(f"Container deployment is not supported in {deployment_name}.")
        if not is_container_deployment and not self._config.supported_package_deployment(deployment_name):
            raise RuntimeError(f"Code package deployment is not supported in {deployment_name}.")

        current_logging_handlers = self.generate_logging_handlers(logging_filename)
        
        # Deserialize FaaS specific config if not already provided
        if not deployment_faas_config:
            # Config.deserialize expects the full config dict for the specific deployment
            # e.g., if deployment_settings = {"name": "aws", "region": "us-east-1", ...},
            # it needs this dict.
            deployment_faas_config = Config.deserialize(deployment_settings, self.cache_client, current_logging_handlers)

        deployment_client_instance = faas_implementations[deployment_name](
            self._config, # Global SeBSConfig
            deployment_faas_config,  # Provider-specific Config
            self.cache_client,
            self.docker_client,
            current_logging_handlers,
        )
        return deployment_client_instance

    def get_deployment_config(
        self,
        deployment_settings: dict, # Renamed from config for clarity
        logging_filename: Optional[str] = None,
    ) -> Config:
        """
        Deserialize a FaaS deployment configuration.

        :param deployment_settings: Dictionary containing the deployment-specific configuration.
        :param logging_filename: Optional filename for logs.
        :return: A deserialized Config object for the FaaS provider.
        """
        current_logging_handlers = self.generate_logging_handlers(logging_filename)
        return Config.deserialize(deployment_settings, self.cache_client, current_logging_handlers)

    def get_experiment_config(self, full_user_config: dict) -> ExperimentConfig:
        """
        Deserialize the experiment-specific part of the user configuration.

        :param full_user_config: The complete user-provided configuration dictionary.
                                 Expected to have an "experiments" key.
        :return: An ExperimentConfig instance.
        """
        # ExperimentConfig.deserialize expects the content of the "experiments" key
        return ExperimentConfig.deserialize(full_user_config.get("experiments", {}))


    def get_experiment(
        self, experiment_name: str, user_config: dict, logging_filename: Optional[str] = None
    ) -> Experiment:
        """
        Get an instance of a specified experiment type.

        :param experiment_name: The name of the experiment to get (e.g., "perf-cost").
        :param user_config: User-provided configuration dictionary.
        :param logging_filename: Optional filename for logs specific to this experiment.
        :return: An initialized Experiment instance.
        :raises RuntimeError: If the experiment type is not supported.
        """
        from sebs.experiments import ( # Local import to avoid circular dependencies at module level
            PerfCost, NetworkPingPong, InvocationOverhead, EvictionModel
        )

        experiment_implementations: Dict[str, Type[Experiment]] = {
            "perf-cost": PerfCost,
            "network-ping-pong": NetworkPingPong,
            "invocation-overhead": InvocationOverhead,
            "eviction-model": EvictionModel,
        }
        if experiment_name not in experiment_implementations:
            raise RuntimeError(f"Experiment {experiment_name} not supported!")
        
        # Experiment constructor expects ExperimentConfig instance
        experiment_settings_obj = self.get_experiment_config(user_config)
        experiment_instance = experiment_implementations[experiment_name](experiment_settings_obj)
        experiment_instance.logging_handlers = self.generate_logging_handlers(logging_filename)
        return experiment_instance

    def get_benchmark(
        self,
        benchmark_name: str, # Renamed from name for clarity
        deployment_client: FaaSSystem, # Renamed from deployment
        experiment_cfg: ExperimentConfig, # Renamed from config
        logging_filename: Optional[str] = None,
    ) -> Benchmark:
        """
        Get a Benchmark instance for a given name, deployment, and configuration.

        Initializes a Benchmark object, which involves finding benchmark code,
        loading its configuration, and interacting with the cache.

        :param benchmark_name: Name of the benchmark.
        :param deployment_client: Initialized FaaS deployment client.
        :param experiment_cfg: The active experiment's configuration.
        :param logging_filename: Optional filename for logs specific to this benchmark.
        :return: An initialized Benchmark instance.
        """
        benchmark_instance = Benchmark(
            benchmark_name,
            deployment_client.name(), # Get deployment name from the client
            experiment_cfg,
            self._config, # Global SeBSConfig
            self._output_dir,
            self.cache_client,
            self.docker_client,
        )
        benchmark_instance.logging_handlers = self.generate_logging_handlers(logging_filename)
        return benchmark_instance

    @staticmethod
    def get_storage_implementation(storage_type: types.Storage) -> Type[PersistentStorage]:
        """
        Get the class for a given self-hosted persistent storage type.

        :param storage_type: A `sebs.types.Storage` enum member.
        :return: The class of the storage implementation (e.g., Minio).
        :raises AssertionError: If the storage type is unknown.
        """
        # Maps storage type enum to its implementation class
        _storage_map = {types.Storage.MINIO: minio.Minio}
        impl_class = _storage_map.get(storage_type)
        assert impl_class is not None, f"Unknown self-hosted storage type: {storage_type}"
        return impl_class

    @staticmethod
    def get_nosql_implementation(storage_type: types.NoSQLStorage) -> Type[NoSQLStorage]:
        """
        Get the class for a given self-hosted NoSQL storage type.

        :param storage_type: A `sebs.types.NoSQLStorage` enum member.
        :return: The class of the NoSQL storage implementation (e.g., ScyllaDB).
        :raises AssertionError: If the NoSQL storage type is unknown.
        """
        _nosql_map = {types.NoSQLStorage.SCYLLADB: scylladb.ScyllaDB}
        impl_class = _nosql_map.get(storage_type)
        assert impl_class is not None, f"Unknown self-hosted NoSQL storage type: {storage_type}"
        return impl_class

    @staticmethod
    def get_storage_config_implementation(storage_type: types.Storage) -> Type[config.PersistentStorageConfig]:
        """
        Get the configuration class for a given self-hosted persistent storage type.

        :param storage_type: A `sebs.types.Storage` enum member.
        :return: The configuration class (e.g., MinioConfig).
        :raises AssertionError: If the storage type is unknown.
        """
        _storage_config_map = {types.Storage.MINIO: config.MinioConfig}
        impl_class = _storage_config_map.get(storage_type)
        assert impl_class is not None, f"Unknown self-hosted storage config type: {storage_type}"
        return impl_class

    @staticmethod
    def get_nosql_config_implementation(storage_type: types.NoSQLStorage) -> Type[config.NoSQLStorageConfig]:
        """
        Get the configuration class for a given self-hosted NoSQL storage type.

        :param storage_type: A `sebs.types.NoSQLStorage` enum member.
        :return: The configuration class (e.g., ScyllaDBConfig).
        :raises AssertionError: If the NoSQL storage type is unknown.
        """
        _nosql_config_map = {types.NoSQLStorage.SCYLLADB: config.ScyllaDBConfig}
        impl_class = _nosql_config_map.get(storage_type)
        assert impl_class is not None, f"Unknown self-hosted NoSQL storage config type: {storage_type}"
        return impl_class

    def shutdown(self):
        """
        Shut down the SeBS client, primarily by shutting down the cache client
        which handles saving any updated configurations.
        """
        self.cache_client.shutdown()

    def __enter__(self):
        """Enter the runtime context related to this object (for `with` statement)."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Exit the runtime context, ensuring shutdown is called.

        :param exc_type: Exception type if an exception occurred in the `with` block.
        :param exc_val: Exception value.
        :param exc_tb: Traceback object.
        """
        self.shutdown()
