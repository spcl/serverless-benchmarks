"""
Module providing the core abstraction for Function-as-a-Service (FaaS) systems.

This module defines the base System class that provides consistent interfaces for
working with different serverless platforms (AWS Lambda, Azure Functions, Google Cloud
Functions, OpenWhisk, etc.). It handles function lifecycle management, code packaging,
deployment, triggering, and metrics collection while abstracting away platform-specific
details.
"""

from abc import ABC
from abc import abstractmethod
from random import randrange
from typing import Dict, List, Optional, Tuple, Type
import uuid

import docker

from sebs.benchmark import Benchmark
from sebs.cache import Cache
from sebs.config import SeBSConfig
from sebs.faas.resources import SystemResources
from sebs.faas.config import Resources
from sebs.faas.function import Function, Trigger, ExecutionResult
from sebs.utils import LoggingBase
from .config import Config


class System(ABC, LoggingBase):
    """
    Abstract base class for FaaS system implementations.
    
    This class provides basic abstractions for all supported FaaS platforms.
    It defines the interface for system initialization, resource management,
    function deployment, code packaging, function invocation, and metrics collection.
    Each cloud provider implements a concrete subclass of this abstract base.
    
    The class handles:
    - System and storage service initialization
    - Creation and updating of serverless functions
    - Function code packaging and deployment
    - Trigger creation and management
    - Metrics collection and error handling
    - Caching of functions to avoid redundant deployments
    - Cold start management
    
    Attributes:
        system_config: Global SeBS configuration
        docker_client: Docker client for building code packages and containers
        cache_client: Cache client for storing function and deployment information
        cold_start_counter: Counter for generating unique function names to force cold starts
        system_resources: Resources manager for the specific cloud platform
    """
    def __init__(
        self,
        system_config: SeBSConfig,
        cache_client: Cache,
        docker_client: docker.client,
        system_resources: SystemResources,
    ):
        """
        Initialize a FaaS system implementation.
        
        Args:
            system_config: Global SeBS configuration settings
            cache_client: Cache client for storing function and deployment information
            docker_client: Docker client for building code packages and containers
            system_resources: Resources manager for the specific cloud platform
        """
        super().__init__()
        self._system_config = system_config
        self._docker_client = docker_client
        self._cache_client = cache_client
        # Initialize with random value to help with cold start detection/forcing
        self._cold_start_counter = randrange(100)
        self._system_resources = system_resources

    @property
    def system_config(self) -> SeBSConfig:
        """
        Get the global SeBS configuration.
        
        Returns:
            SeBSConfig: The system configuration
        """
        return self._system_config

    @property
    def docker_client(self) -> docker.client:
        """
        Get the Docker client.
        
        Returns:
            docker.client: The Docker client
        """
        return self._docker_client

    @property
    def cache_client(self) -> Cache:
        """
        Get the cache client.
        
        Returns:
            Cache: The cache client
        """
        return self._cache_client

    @property
    def cold_start_counter(self) -> int:
        """
        Get the cold start counter.
        
        This counter is used in function name generation to help force cold starts
        by creating new function instances with different names.
        
        Returns:
            int: The current cold start counter value
        """
        return self._cold_start_counter

    @cold_start_counter.setter
    def cold_start_counter(self, val: int):
        """
        Set the cold start counter.
        
        Args:
            val: The new counter value
        """
        self._cold_start_counter = val

    @property
    @abstractmethod
    def config(self) -> Config:
        """
        Get the platform-specific configuration.
        
        Returns:
            Config: The platform-specific configuration
        """
        pass

    @property
    def system_resources(self) -> SystemResources:
        """
        Get the platform-specific resources manager.
        
        Returns:
            SystemResources: The resources manager
        """
        return self._system_resources

    @staticmethod
    @abstractmethod
    def function_type() -> "Type[Function]":
        """
        Get the platform-specific Function class type.
        
        Returns:
            Type[Function]: The Function class for this platform
        """
        pass

    def find_deployments(self) -> List[str]:
        """
        Find existing deployments in the cloud platform.
        
        Default implementation uses storage buckets to identify deployments.
        This can be overridden by platform-specific implementations, e.g.,
        Azure that looks for unique storage accounts.
        
        Returns:
            List[str]: List of existing deployment resource IDs
        """
        return self.system_resources.get_storage().find_deployments()

    def initialize_resources(self, select_prefix: Optional[str]):
        """
        Initialize cloud resources for the deployment.
        
        This method either:
        1. Uses an existing resource ID from configuration
        2. Finds and reuses an existing deployment matching the prefix
        3. Creates a new unique resource ID and initializes resources
        
        Args:
            select_prefix: Optional prefix to match when looking for existing deployments
        """
        # User provided resources or found in cache
        if self.config.resources.has_resources_id:
            self.logging.info(
                f"Using existing resource name: {self.config.resources.resources_id}."
            )
            return

        # Now search for existing resources
        deployments = self.find_deployments()

        # If a prefix is specified, we find the first matching resource ID
        if select_prefix is not None:
            for dep in deployments:
                if select_prefix in dep:
                    self.logging.info(
                        f"Using existing deployment {dep} that matches prefix {select_prefix}!"
                    )
                    self.config.resources.resources_id = dep
                    return

        # We warn users that we create a new resource ID
        # They can use them with a new config
        if len(deployments) > 0:
            self.logging.warning(
                f"We found {len(deployments)} existing deployments! "
                "If you want to use any of them, please abort, and "
                "provide the resource id in your input config."
            )
            self.logging.warning("Deployment resource IDs in the cloud: " f"{deployments}")

        # Create a new unique resource ID
        res_id = ""
        if select_prefix is not None:
            res_id = f"{select_prefix}-{str(uuid.uuid1())[0:8]}"
        else:
            res_id = str(uuid.uuid1())[0:8]
        self.config.resources.resources_id = res_id
        self.logging.info(f"Generating unique resource name {res_id}")
        
        # Ensure that the bucket is created - this allocates the new resource
        self.system_resources.get_storage().get_bucket(Resources.StorageBucketType.BENCHMARKS)

    def initialize(self, config: Dict[str, str] = {}, resource_prefix: Optional[str] = None):
        """
        Initialize the system.
        
        After this call completes, the local or remote FaaS system should be ready
        to allocate functions, manage storage resources, and invoke functions.
        
        Args:
            config: System-specific parameters
            resource_prefix: Optional prefix for resource naming
        """
        pass

    @abstractmethod
    def package_code(
        self,
        directory: str,
        language_name: str,
        language_version: str,
        architecture: str,
        benchmark: str,
        is_cached: bool,
        container_deployment: bool,
    ) -> Tuple[str, int, str]:
        """
        Apply system-specific code packaging to prepare a deployment package.
        
        The benchmark creates a code directory with the following structure:
        - [benchmark sources]
        - [benchmark resources]
        - [dependence specification], e.g. requirements.txt or package.json
        - [handlers implementation for the language and deployment]

        This step transforms that structure to fit platform-specific deployment
        requirements, such as creating a zip file for AWS or container image.
        
        Args:
            directory: Path to the code directory
            language_name: Programming language name
            language_version: Programming language version
            architecture: Target architecture (e.g., 'x64', 'arm64')
            benchmark: Benchmark name
            is_cached: Whether the code is cached
            container_deployment: Whether to package for container deployment

        Returns:
            Tuple containing:
            - Path to packaged code
            - Size of the package in bytes
            - Container URI (if container deployment, otherwise empty string)
        """
        pass

    @abstractmethod
    def create_function(
        self,
        code_package: Benchmark,
        func_name: str,
        container_deployment: bool,
        container_uri: str,
    ) -> Function:

        """
        Create a new function in the FaaS platform.
        The implementation is responsible for creating all necessary
        cloud resources.

        Args:
            code_package: Benchmark containing the function code
            func_name: Name of the function
            container_deployment: Whether to deploy as a container
            container_uri: URI of the container image

        Returns:
            Function: Created function instance

        Raises:
            NotImplementedError: If container deployment is requested but not supported
        """
        pass

    @abstractmethod
    def cached_function(self, function: Function):
        """
        Perform any necessary operations for a cached function.
        
        This method is called when a function is found in the cache. It may perform
        platform-specific operations such as checking if the function still exists
        in the cloud, updating permissions, etc.
        
        Args:
            function: The cached function instance
        """
        pass

    @abstractmethod
    def update_function(
        self,
        function: Function,
        code_package: Benchmark,
        container_deployment: bool,
        container_uri: str,
    ):
        """
        Update an existing function in the FaaS platform.

        Args:
            function: Existing function instance to update
            code_package: New benchmark containing the function code
            container_deployment: Whether to deploy as a container
            container_uri: URI of the container image

        Raises:
            NotImplementedError: If container deployment is requested but not supported
        """
        pass

    def get_function(self, code_package: Benchmark, func_name: Optional[str] = None) -> Function:
        """
        Get or create a function for a benchmark.
        
        This method handles the complete function creation/update workflow:
        
        1. If a cached function with the given name exists and code has not changed,
           returns the existing function
        2. If a cached function exists but the code has changed, updates the
           function with the new code
        3. If no cached function exists, creates a new function
        
        Args:
            code_package: The benchmark containing the function code
            func_name: Optional name for the function (will be generated if not provided)
            
        Returns:
            Function: The function instance
            
        Raises:
            Exception: If the language version is not supported by this platform
        """
        # Verify language version compatibility
        if code_package.language_version not in self.system_config.supported_language_versions(
            self.name(), code_package.language_name, code_package.architecture
        ):
            raise Exception(
                "Unsupported {language} version {version} in {system}!".format(
                    language=code_package.language_name,
                    version=code_package.language_version,
                    system=self.name(),
                )
            )

        # Generate function name if not provided
        if not func_name:
            func_name = self.default_function_name(code_package)
            
        # Build the code package
        rebuilt, _, container_deployment, container_uri = code_package.build(self.package_code)

        # Check if function exists in cache
        functions = code_package.functions
        is_function_cached = not (not functions or func_name not in functions)
        
        if is_function_cached:
            # Retrieve function from cache
            cached_function = functions[func_name]
            code_location = code_package.code_location

            try:
                function = self.function_type().deserialize(cached_function)
            except RuntimeError as e:
                self.logging.error(
                    f"Cached function {cached_function['name']} is no longer available."
                )
                self.logging.error(e)
                is_function_cached = False

        # Create new function if not cached or deserialize failed
        if not is_function_cached:
            msg = (
                "function name not provided."
                if not func_name
                else "function {} not found in cache.".format(func_name)
            )
            self.logging.info("Creating new function! Reason: " + msg)
            function = self.create_function(
                code_package, func_name, container_deployment, container_uri
            )
            self.cache_client.add_function(
                deployment_name=self.name(),
                language_name=code_package.language_name,
                code_package=code_package,
                function=function,
            )
            code_package.query_cache()
            return function
        else:
            # Handle existing function
            assert function is not None
            self.cached_function(function)
            self.logging.info(
                "Using cached function {fname} in {loc}".format(fname=func_name, loc=code_location)
            )
            
            # Check if code needs to be updated
            if function.code_package_hash != code_package.hash or rebuilt:
                if function.code_package_hash != code_package.hash:
                    self.logging.info(
                        f"Cached function {func_name} with hash "
                        f"{function.code_package_hash} is not up to date with "
                        f"current build {code_package.hash} in "
                        f"{code_location}, updating cloud version!"
                    )
                if rebuilt:
                    self.logging.info(
                        f"Enforcing rebuild and update of cached function "
                        f"{func_name} with hash {function.code_package_hash}."
                    )
                    
                # Update function code
                self.update_function(function, code_package, container_deployment, container_uri)
                function.code_package_hash = code_package.hash
                function.updated_code = True
                self.cache_client.add_function(
                    deployment_name=self.name(),
                    language_name=code_package.language_name,
                    code_package=code_package,
                    function=function,
                )
                code_package.query_cache()
                
            # Check if configuration needs to be updated
            elif self.is_configuration_changed(function, code_package):
                self.update_function_configuration(function, code_package)
                self.cache_client.update_function(function)
                code_package.query_cache()
            else:
                self.logging.info(f"Cached function {func_name} is up to date.")
                
            return function

    @abstractmethod
    def update_function_configuration(self, cached_function: Function, benchmark: Benchmark):
        """
        Update the configuration of an existing function.
        
        This method is called when a function's code is up-to-date but its
        configuration (memory, timeout, etc.) needs to be updated.
        
        Args:
            cached_function: The function to update
            benchmark: The benchmark containing the new configuration
        """
        pass

    def is_configuration_changed(self, cached_function: Function, benchmark: Benchmark) -> bool:
        """
        Check if a function's configuration needs to be updated.
        
        This function checks for common function parameters to verify if their
        values are still up to date with the benchmark configuration.
        
        Args:
            cached_function: The existing function
            benchmark: The benchmark with potential new configuration
            
        Returns:
            bool: True if configuration has changed, False otherwise
        """
        changed = False
        
        # Check common configuration attributes
        for attr in ["timeout", "memory"]:
            new_val = getattr(benchmark.benchmark_config, attr)
            old_val = getattr(cached_function.config, attr)
            if new_val != old_val:
                self.logging.info(
                    f"Updating function configuration due to changed attribute {attr}: "
                    f"cached function has value {old_val} whereas {new_val} has been requested."
                )
                changed = True
                setattr(cached_function.config, attr, new_val)

        # Check language/runtime attributes
        for lang_attr in [["language"] * 2, ["language_version", "version"]]:
            new_val = getattr(benchmark, lang_attr[0])
            old_val = getattr(cached_function.config.runtime, lang_attr[1])
            if new_val != old_val:
                # FIXME: should this even happen? we should never pick the function with
                # different runtime - that should be encoded in the name
                self.logging.info(
                    f"Updating function configuration due to changed runtime attribute {attr}: "
                    f"cached function has value {old_val} whereas {new_val} has been requested."
                )
                changed = True
                setattr(cached_function.config.runtime, lang_attr[1], new_val)

        return changed

    @abstractmethod
    def default_function_name(
        self, code_package: Benchmark, resources: Optional[Resources] = None
    ) -> str:
        """
        Generate a default function name for a benchmark.
        
        Args:
            code_package: The benchmark to generate a name for
            resources: Optional resources configuration
            
        Returns:
            str: Generated function name
        """
        pass

    @abstractmethod
    def enforce_cold_start(self, functions: List[Function], code_package: Benchmark):
        """
        Force cold starts for the specified functions.
        
        This method implements platform-specific techniques to ensure that
        subsequent invocations of the functions will be cold starts.
        
        Args:
            functions: List of functions to enforce cold starts for
            code_package: The benchmark associated with the functions
        """
        pass

    @abstractmethod
    def download_metrics(
        self,
        function_name: str,
        start_time: int,
        end_time: int,
        requests: Dict[str, ExecutionResult],
        metrics: dict,
    ):
        """
        Download function metrics from the cloud platform.
        
        Args:
            function_name: Name of the function to get metrics for
            start_time: Start timestamp for metrics collection
            end_time: End timestamp for metrics collection
            requests: Dictionary of execution results
            metrics: Dictionary to store the downloaded metrics
        """
        pass

    @abstractmethod
    def create_trigger(self, function: Function, trigger_type: Trigger.TriggerType) -> Trigger:
        """
        Create a trigger for a function.
        
        Args:
            function: The function to create a trigger for
            trigger_type: Type of trigger to create
            
        Returns:
            Trigger: The created trigger
        """
        pass

    def disable_rich_output(self):
        """
        Disable rich output for platforms that support it.
        
        This is mostly used in testing environments or CI pipelines.
        """
        pass

    @abstractmethod
    def shutdown(self) -> None:
        """
        Shutdown the FaaS system.
        
        Closes connections, stops local instances, and updates the cache.
        This should be called when the system is no longer needed.
        """
        try:
            self.cache_client.lock()
            self.config.update_cache(self.cache_client)
        finally:
            self.cache_client.unlock()

    @staticmethod
    @abstractmethod
    def name() -> str:
        """
        Get the name of the platform.
        
        Returns:
            str: Platform name (e.g., 'aws', 'azure', 'gcp')
        """
        pass
