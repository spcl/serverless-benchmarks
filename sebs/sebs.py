"""Main SeBS (Serverless Benchmarking Suite) client implementation.

This module provides the main interface for the Serverless Benchmarking Suite,
offering a unified API for deploying, executing, and benchmarking serverless
functions across multiple cloud providers and locally. It manages:

- Deployment client creation for different platforms (AWS, Azure, GCP, OpenWhisk, local)
- Benchmark execution and configuration
- Experiment setup and execution
- Storage access (object storage and NoSQL)
- Caching and Docker management
- Logging and output handling

The SeBS client is the central point of interaction for both the CLI and programmatic use.
"""

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
    """Main client for the Serverless Benchmarking Suite.

    This class provides the primary interface for interacting with the benchmarking
    suite. It manages deployment clients, benchmarks, experiments, and resources.
    It handles caching, logging, and provides factory methods for creating the
    various components needed for benchmarking.

    Attributes:
        cache_client: Client for managing cached artifacts (code packages, etc.)
        docker_client: Docker client for container operations
        output_dir: Directory for storing output files and logs
        verbose: Whether to enable verbose logging
        logging_filename: Default log file name
        config: Global SeBS configuration
    """

    @property
    def cache_client(self) -> Cache:
        """Get the cache client.

        Returns:
            Cache client for managing cached artifacts
        """
        return self._cache_client

    @property
    def docker_client(self) -> docker.client:
        """Get the Docker client.

        Returns:
            Docker client for container operations
        """
        return self._docker_client

    @property
    def output_dir(self) -> str:
        """Get the output directory.

        Returns:
            Path to the output directory
        """
        return self._output_dir

    @property
    def verbose(self) -> bool:
        """Get the verbose flag.

        Returns:
            Whether verbose logging is enabled
        """
        return self._verbose

    @property
    def logging_filename(self) -> Optional[str]:
        """Get the default logging filename.

        Returns:
            Default logging filename or None if not set
        """
        return self._logging_filename

    @property
    def config(self) -> SeBSConfig:
        """Get the global SeBS configuration.

        Returns:
            Global configuration object
        """
        return self._config

    def generate_logging_handlers(self, logging_filename: Optional[str] = None) -> LoggingHandlers:
        """Generate logging handlers for a specific file.

        This method creates or retrieves cached logging handlers for a given filename.
        If no filename is provided, the default logging filename is used.

        Args:
            logging_filename: Optional filename for logs, defaults to self.logging_filename

        Returns:
            LoggingHandlers configured for the specified file
        """
        filename = logging_filename if logging_filename else self.logging_filename
        if filename in self._handlers:
            return self._handlers[filename]
        else:
            handlers = LoggingHandlers(verbose=self.verbose, filename=filename)
            self._handlers[filename] = handlers
            return handlers

    def __init__(
        self,
        cache_dir: str,
        output_dir: str,
        verbose: bool = False,
        logging_filename: Optional[str] = None,
    ):
        """Initialize the SeBS client.

        Creates a new SeBS client with the specified configuration. This sets up:
        - Docker client
        - Cache client
        - Global configuration
        - Logging handlers
        - Output directory

        Args:
            cache_dir: Directory for caching artifacts
            output_dir: Directory for storing output files and logs
            verbose: Whether to enable verbose logging (default: False)
            logging_filename: Default log file name (default: None)
        """
        super().__init__()
        self._docker_client = docker.from_env()
        self._cache_client = Cache(cache_dir, self._docker_client)
        self._config = SeBSConfig()
        self._output_dir = output_dir
        self._verbose = verbose
        self._logging_filename = logging_filename
        self._handlers: Dict[Optional[str], LoggingHandlers] = {}
        self.logging_handlers = self.generate_logging_handlers()

        # Create output directory if it doesn't exist
        os.makedirs(self.output_dir, exist_ok=True)

    def ignore_cache(self):
        """Configure the cache to only store code packages.

        After calling this method, the cache will only store code packages
        and won't update or use cached functions and storage. This is useful
        when you want to ensure that functions are redeployed and storage
        is recreated, but still want to reuse code packages.
        """
        self._cache_client.ignore_storage = True
        self._cache_client.ignore_functions = True

    def get_deployment(
        self,
        config: dict,
        logging_filename: Optional[str] = None,
        deployment_config: Optional[Config] = None,
    ) -> FaaSSystem:
        """Get a deployment client for a specific cloud platform.

        This method creates and returns a deployment client for the specified
        cloud platform. It validates that the requested platform and configuration
        are supported, and initializes the client with the appropriate resources.

        The method dynamically imports the necessary modules for each platform
        based on what's available in the environment, determined by has_platform().

        Args:
            config: Configuration dictionary with deployment and experiment settings
            logging_filename: Optional filename for logs
            deployment_config: Optional pre-configured deployment config

        Returns:
            An initialized FaaS system deployment client

        Raises:
            RuntimeError: If the requested deployment is not supported or if the
                         configuration is invalid (unsupported architecture,
                         deployment type, etc.)
        """
        dep_config = config["deployment"]
        name = dep_config["name"]
        implementations: Dict[str, Type[FaaSSystem]] = {"local": Local}

        # Dynamically import platform-specific modules as needed
        if has_platform("aws"):
            from sebs.aws import AWS

            implementations["aws"] = AWS
        if has_platform("azure"):
            from sebs.azure.azure import Azure

            implementations["azure"] = Azure
        if has_platform("gcp"):
            from sebs.gcp import GCP

            implementations["gcp"] = GCP
        if has_platform("openwhisk"):
            from sebs.openwhisk import OpenWhisk

            implementations["openwhisk"] = OpenWhisk

        # Validate deployment platform
        if name not in implementations:
            raise RuntimeError("Deployment {name} not supported!".format(name=name))

        # Validate architecture
        if config["experiments"]["architecture"] not in self._config.supported_architecture(name):
            raise RuntimeError(
                "{architecture} is not supported in {name}".format(
                    architecture=config["experiments"]["architecture"], name=name
                )
            )

        # Validate deployment type - container
        if config["experiments"][
            "container_deployment"
        ] and not self._config.supported_container_deployment(name):
            raise RuntimeError(f"Container deployment is not supported in {name}.")

        # Validate deployment type - package
        if not config["experiments"][
            "container_deployment"
        ] and not self._config.supported_package_deployment(name):
            raise RuntimeError(f"Code package deployment is not supported in {name}.")

        # Set up logging and create deployment configuration
        handlers = self.generate_logging_handlers(logging_filename)
        if not deployment_config:
            deployment_config = Config.deserialize(dep_config, self.cache_client, handlers)

        # Create and return the deployment client
        deployment_client = implementations[name](
            self._config,
            deployment_config,  # type: ignore
            self.cache_client,
            self.docker_client,
            handlers,
        )
        return deployment_client

    def get_deployment_config(
        self,
        config: dict,
        logging_filename: Optional[str] = None,
    ) -> Config:
        """Create a deployment configuration from a dictionary.

        This method deserializes a deployment configuration from a dictionary,
        setting up logging handlers and connecting it to the cache client.

        Args:
            config: Configuration dictionary
            logging_filename: Optional filename for logs

        Returns:
            A deserialized deployment configuration object
        """
        handlers = self.generate_logging_handlers(logging_filename)
        return Config.deserialize(config, self.cache_client, handlers)

    def get_experiment_config(self, config: dict) -> ExperimentConfig:
        """Create an experiment configuration from a dictionary.

        This method deserializes an experiment configuration from a dictionary.
        The experiment configuration contains settings specific to the
        experiment being run, such as the number of iterations, timeout, etc.

        Args:
            config: Configuration dictionary

        Returns:
            A deserialized experiment configuration object
        """
        return ExperimentConfig.deserialize(config)

    def get_experiment(
        self, experiment_type: str, config: dict, logging_filename: Optional[str] = None
    ) -> Experiment:
        """Get an experiment implementation for a specific experiment type.

        This method creates and returns an experiment implementation for the
        specified experiment type. It validates that the requested experiment
        type is supported and initializes the experiment with the appropriate
        configuration.

        Args:
            experiment_type: Type of experiment to create (e.g., "perf-cost")
            config: Configuration dictionary
            logging_filename: Optional filename for logs

        Returns:
            An initialized experiment implementation

        Raises:
            RuntimeError: If the requested experiment type is not supported
        """
        from sebs.experiments import (
            Experiment,
            PerfCost,
            NetworkPingPong,
            InvocationOverhead,
            EvictionModel,
        )

        # Map of supported experiment types to their implementations
        implementations: Dict[str, Type[Experiment]] = {
            "perf-cost": PerfCost,
            "network-ping-pong": NetworkPingPong,
            "invocation-overhead": InvocationOverhead,
            "eviction-model": EvictionModel,
        }

        # Validate experiment type
        if experiment_type not in implementations:
            raise RuntimeError(f"Experiment {experiment_type} not supported!")

        # Create and configure the experiment
        experiment = implementations[experiment_type](self.get_experiment_config(config))
        experiment.logging_handlers = self.generate_logging_handlers(
            logging_filename=logging_filename
        )
        return experiment

    def get_benchmark(
        self,
        name: str,
        deployment: FaaSSystem,
        config: ExperimentConfig,
        logging_filename: Optional[str] = None,
    ) -> Benchmark:
        """Get a benchmark implementation for a specific benchmark.

        This method creates and returns a benchmark implementation for the
        specified benchmark name. It configures the benchmark with the
        appropriate deployment, configuration, and resources.

        Args:
            name: Name of the benchmark to create (e.g., "210.thumbnailer")
            deployment: FaaS system deployment client
            config: Experiment configuration
            logging_filename: Optional filename for logs

        Returns:
            An initialized benchmark implementation
        """
        # Create and configure the benchmark
        benchmark = Benchmark(
            name,
            deployment.name(),
            config,
            self._config,
            self._output_dir,
            self.cache_client,
            self.docker_client,
        )

        # Set up logging
        benchmark.logging_handlers = self.generate_logging_handlers(
            logging_filename=logging_filename
        )
        return benchmark

    @staticmethod
    def get_storage_implementation(storage_type: types.Storage) -> Type[PersistentStorage]:
        """Get a storage implementation for a specific storage type.

        This method returns the class for a persistent storage implementation
        for the specified storage type.

        Args:
            storage_type: Type of storage to get implementation for

        Returns:
            Storage implementation class

        Raises:
            AssertionError: If the requested storage type is not supported
        """
        _storage_implementations = {types.Storage.MINIO: minio.Minio}
        impl = _storage_implementations.get(storage_type)
        assert impl, f"Storage type {storage_type} not supported"
        return impl

    @staticmethod
    def get_nosql_implementation(storage_type: types.NoSQLStorage) -> Type[NoSQLStorage]:
        """Get a NoSQL storage implementation for a specific storage type.

        This method returns the class for a NoSQL storage implementation
        for the specified storage type.

        Args:
            storage_type: Type of NoSQL storage to get implementation for

        Returns:
            NoSQL storage implementation class

        Raises:
            AssertionError: If the requested storage type is not supported
        """
        _storage_implementations = {types.NoSQLStorage.SCYLLADB: scylladb.ScyllaDB}
        impl = _storage_implementations.get(storage_type)
        assert impl, f"NoSQL storage type {storage_type} not supported"
        return impl

    @staticmethod
    def get_storage_config_implementation(storage_type: types.Storage):
        """Get a storage configuration implementation for a specific storage type.

        This method returns the class for a storage configuration implementation
        for the specified storage type.

        Args:
            storage_type: Type of storage to get configuration for

        Returns:
            Storage configuration implementation class

        Raises:
            AssertionError: If the requested storage type is not supported
        """
        _storage_implementations = {types.Storage.MINIO: config.MinioConfig}
        impl = _storage_implementations.get(storage_type)
        assert impl, f"Storage configuration for type {storage_type} not supported"
        return impl

    @staticmethod
    def get_nosql_config_implementation(storage_type: types.NoSQLStorage):
        """Get a NoSQL configuration implementation for a specific storage type.

        This method returns the class for a NoSQL configuration implementation
        for the specified storage type.

        Args:
            storage_type: Type of NoSQL storage to get configuration for

        Returns:
            NoSQL configuration implementation class

        Raises:
            AssertionError: If the requested storage type is not supported
        """
        _storage_implementations = {types.NoSQLStorage.SCYLLADB: config.ScyllaDBConfig}
        impl = _storage_implementations.get(storage_type)
        assert impl, f"NoSQL configuration for type {storage_type} not supported"
        return impl

    def shutdown(self):
        """Shutdown the SeBS client and release resources.

        This method shuts down the cache client and releases any resources
        that need to be cleaned up when the client is no longer needed.
        It is automatically called when using the client as a context manager.
        """
        self.cache_client.shutdown()

    def __enter__(self):
        """Enter context manager.

        This method allows the SeBS client to be used as a context manager
        using the 'with' statement, which ensures proper cleanup of resources.

        Returns:
            The SeBS client instance
        """
        return self

    def __exit__(self, exc_type=None, exc_val=None, exc_tb=None):
        """Exit context manager.

        This method is called when exiting a 'with' block. It ensures that
        resources are properly cleaned up by calling shutdown().

        Args:
            exc_type: Exception type if an exception occurred, None otherwise
            exc_val: Exception value if an exception occurred, None otherwise
            exc_tb: Exception traceback if an exception occurred, None otherwise
        """
        self.shutdown()
