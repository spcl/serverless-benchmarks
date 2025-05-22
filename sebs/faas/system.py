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

"""
This module defines the abstract base class `System` for FaaS (Function-as-a-Service)
systems. It provides a common interface for initializing the system, managing
storage services, creating and updating serverless functions, and querying
logging and measurement services to obtain error messages and performance data.
"""


class System(ABC, LoggingBase):
    """
    Abstract base class for FaaS system interactions.

    This class defines the core functionalities required to interact with a FaaS
    platform, such as deploying functions, managing resources, and invoking functions.
    Subclasses implement these functionalities for specific FaaS providers (e.g., AWS Lambda,
    Azure Functions).
    """
    def __init__(
        self,
        system_config: SeBSConfig,
        cache_client: Cache,
        docker_client: docker.client,
        system_resources: SystemResources,
    ):
        """
        Initialize a FaaS System instance.

        :param system_config: The global SeBS configuration.
        :param cache_client: The cache client for storing and retrieving deployment information.
        :param docker_client: The Docker client for image and container operations.
        :param system_resources: Provider-specific system resources manager.
        """
        super().__init__()
        self._system_config = system_config
        self._docker_client = docker_client
        self._cache_client = cache_client
        self._cold_start_counter = randrange(100) # Used to try and force cold starts
        self._system_resources = system_resources

    @property
    def system_config(self) -> SeBSConfig:
        """The global SeBS configuration."""
        return self._system_config

    @property
    def docker_client(self) -> docker.client:
        """The Docker client instance."""
        return self._docker_client

    @property
    def cache_client(self) -> Cache:
        """The cache client instance."""
        return self._cache_client

    @property
    def cold_start_counter(self) -> int:
        """
        A counter used in attempts to enforce cold starts.
        Its value might be incorporated into function environment variables.
        """
        return self._cold_start_counter

    @cold_start_counter.setter
    def cold_start_counter(self, val: int):
        """Set the cold start counter."""
        self._cold_start_counter = val

    @property
    @abstractmethod
    def config(self) -> Config:
        """Provider-specific configuration for this FaaS system."""
        pass

    @property
    def system_resources(self) -> SystemResources:
        """Provider-specific system resources manager."""
        return self._system_resources

    @staticmethod
    @abstractmethod
    def function_type() -> "Type[Function]":
        """
        Return the concrete Function subclass associated with this FaaS system.

        :return: The class type of the function (e.g., AWSLambdaFunction, AzureFunction).
        """
        pass

    def find_deployments(self) -> List[str]:
        """
        Find existing SeBS deployments on the FaaS platform.

        Default implementation uses storage buckets (e.g., S3, Azure Blob) to identify
        deployments by looking for buckets matching a SeBS naming pattern.
        This can be overridden by subclasses if a different discovery mechanism is needed
        (e.g., Azure uses resource groups).

        :return: A list of deployment identifiers (resource prefixes).
        """
        return self.system_resources.get_storage().find_deployments()

    def initialize_resources(self, select_prefix: Optional[str]):
        """
        Initialize or select resources for the current SeBS deployment.

        If a resource ID is already configured or found in the cache, it's used.
        Otherwise, it searches for existing deployments. If a `select_prefix` is given,
        it tries to match an existing deployment. If no suitable existing deployment
        is found or specified, a new unique resource ID is generated.
        Ensures that the benchmark storage bucket is created, which often allocates
        the new resource set if one was generated.

        :param select_prefix: Optional prefix to select an existing deployment.
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

        # create
        res_id = ""
        if select_prefix is not None:
            res_id = f"{select_prefix}-{str(uuid.uuid1())[0:8]}"
        else:
            res_id = str(uuid.uuid1())[0:8]
        self.config.resources.resources_id = res_id
        self.logging.info(f"Generating unique resource name {res_id}")
        # ensure that the bucket is created - this allocates the new resource
        self.system_resources.get_storage().get_bucket(Resources.StorageBucketType.BENCHMARKS)

    def initialize(self, config: Dict[str, str] = {}, resource_prefix: Optional[str] = None):
        """
        Initialize the FaaS system.

        After this call, the local or remote FaaS system should be ready to
        allocate functions, manage storage resources, and invoke functions.
        Subclasses should override this to perform provider-specific initialization.

        :param config: System-specific parameters (currently not widely used by subclasses).
        :param resource_prefix: Optional prefix for naming/selecting resources.
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
        Apply the system-specific code packaging routine to build a benchmark.

        The benchmark build process creates a code directory with a standard structure:
        - Benchmark source files
        - Benchmark resource files
        - Dependency specification (e.g., requirements.txt, package.json)
        - Language-specific handlers for the FaaS platform

        This method adapts this standard structure to fit the specific deployment
        requirements of the FaaS provider (e.g., creating a zip file for AWS Lambda,
        arranging files for Azure Functions).

        :param directory: Path to the code directory prepared by the benchmark build.
        :param language_name: Programming language name (e.g., "python").
        :param language_version: Programming language version (e.g., "3.8").
        :param architecture: Target CPU architecture (e.g., "x64", "arm64").
        :param benchmark: Name of the benchmark.
        :param is_cached: Whether the benchmark code is considered cached by SeBS.
        :param container_deployment: Whether to package for container-based deployment.
        :return: A tuple containing:
            - Path to the packaged code (e.g., path to zip file or prepared directory).
            - Size of the package in bytes.
            - Container image URI if `container_deployment` is True, else an empty string.
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
        Create a new function on the FaaS platform.

        The implementation is responsible for creating all necessary cloud resources
        (e.g., function definition, IAM roles, triggers if applicable).

        :param code_package: Benchmark object containing code and configuration.
        :param func_name: The desired name for the function on the FaaS platform.
        :param container_deployment: True if deploying as a container image.
        :param container_uri: URI of the container image if `container_deployment` is True.
        :return: A Function object representing the created function.
        :raises NotImplementedError: If container deployment is requested but not supported.
        """
        pass

    @abstractmethod
    def cached_function(self, function: Function):
        """
        Perform any necessary setup or validation for a function retrieved from cache.

        This might involve, for example, re-initializing transient client objects
        or ensuring associated resources (like triggers) are correctly configured.

        :param function: The Function object retrieved from cache.
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
        Update an existing function on the FaaS platform with new code or configuration.

        :param function: The existing Function object to update.
        :param code_package: Benchmark object containing the new code and configuration.
        :param container_deployment: True if deploying as a container image.
        :param container_uri: URI of the new container image if `container_deployment` is True.
        :raises NotImplementedError: If container deployment is requested but not supported.
        """
        pass

    def get_function(self, code_package: Benchmark, func_name: Optional[str] = None) -> Function:
        """
        Get or create a FaaS function for a given benchmark.

        Handles the following logic:
        a) If a cached function with the given name exists and its code hash matches
           the current benchmark code, return the cached function (after potential
           configuration checks/updates via `cached_function` and `is_configuration_changed`).
        b) If a cached function exists but its code hash differs or if `code_package.build`
           indicates a rebuild occurred, update the function in the cloud.
        c) If no cached function is found, create a new function.

        Benchmark code is built (via `code_package.build`) before these steps.
        The build might be skipped if source code hasn't changed and no update is forced.

        :param code_package: The Benchmark object.
        :param func_name: Optional name for the function. If None, a default name is generated.
        :return: The Function object (either retrieved, updated, or newly created).
        :raises Exception: If the language version is not supported by the FaaS system.
        """
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

        if not func_name:
            func_name = self.default_function_name(code_package)
        rebuilt, _, container_deployment, container_uri = code_package.build(self.package_code)

        """
            There's no function with that name?
            a) yes -> create new function. Implementation might check if a function
            with that name already exists in the cloud and update its code.
            b) no -> retrieve function from the cache. Function code in cloud will
            be updated if the local version is different.
        """
        functions = code_package.functions

        is_function_cached = not (not functions or func_name not in functions)
        function: Optional[Function] = None # Ensure function is defined for later assert
        if is_function_cached:
            # retrieve function
            cached_function_data = functions[func_name] # type: ignore
            code_location = code_package.code_location

            try:
                function = self.function_type().deserialize(cached_function_data)
            except RuntimeError as e:
                self.logging.error(
                    f"Cached function {cached_function_data['name']} is no longer available."
                )
                self.logging.error(e)
                is_function_cached = False
                function = None # Explicitly set to None on error

        if not is_function_cached or function is None: # Check if function is None
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
            assert function is not None # Should be true if is_function_cached was true and deserialize succeeded
            self.cached_function(function)
            self.logging.info(
                "Using cached function {fname} in {loc}".format(fname=func_name, loc=code_package.code_location)
            )
            # is the function up-to-date?
            if function.code_package_hash != code_package.hash or rebuilt:
                if function.code_package_hash != code_package.hash:
                    self.logging.info(
                        f"Cached function {func_name} with hash "
                        f"{function.code_package_hash} is not up to date with "
                        f"current build {code_package.hash} in "
                        f"{code_package.code_location}, updating cloud version!"
                    )
                if rebuilt:
                    self.logging.info(
                        f"Enforcing rebuild and update of of cached function "
                        f"{func_name} with hash {function.code_package_hash}."
                    )
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
            # code up to date, but configuration needs to be updated
            # FIXME: detect change in function config
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
        Update the configuration of an existing cached function on the FaaS platform.

        This is called when the function's code hasn't changed, but its configuration
        (e.g., memory, timeout, environment variables) needs to be updated based on
        the current benchmark settings.

        :param cached_function: The Function object (retrieved from cache) to update.
        :param benchmark: The Benchmark object providing the new configuration.
        """
        pass

    def is_configuration_changed(self, cached_function: Function, benchmark: Benchmark) -> bool:
        """
        Check if common function parameters (timeout, memory, runtime) have changed
        between a cached function and the current benchmark configuration.

        :param cached_function: The cached Function object.
        :param benchmark: The current Benchmark object.
        :return: True if any configuration parameter has changed, False otherwise.
        """
        changed = False
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

        # Check language and language_version from benchmark against runtime in FunctionConfig
        # The lang_attr mapping was a bit complex; simplifying the logic.
        # benchmark.language is Language enum, cached_function.config.runtime.language is Language enum
        if benchmark.language != cached_function.config.runtime.language:
            self.logging.info(
                f"Updating function configuration due to changed runtime attribute language: "
                f"cached function has value {cached_function.config.runtime.language.value} "
                f"whereas {benchmark.language.value} has been requested."
            )
            changed = True
            # This change might be problematic if the runtime object is shared or immutable in parts
            # For a dataclass, direct assignment should be fine if Runtime is mutable or a new one is set.
            cached_function.config.runtime.language = benchmark.language

        if benchmark.language_version != cached_function.config.runtime.version:
            self.logging.info(
                f"Updating function configuration due to changed runtime attribute version: "
                f"cached function has value {cached_function.config.runtime.version} "
                f"whereas {benchmark.language_version} has been requested."
            )
            changed = True
            cached_function.config.runtime.version = benchmark.language_version
        # FIXME: Also need to check architecture: benchmark._experiment_config._architecture vs cached_function.config.architecture
        return changed

    @abstractmethod
    def default_function_name(
        self, code_package: Benchmark, resources: Optional[Resources] = None
    ) -> str:
        """
        Generate a default name for a function based on the benchmark and resources.

        Provider-specific naming conventions should be applied here.

        :param code_package: The Benchmark object.
        :param resources: Optional Resources object (may influence naming, e.g., resource prefix).
        :return: The generated default function name.
        """
        pass

    @abstractmethod
    def enforce_cold_start(self, functions: List[Function], code_package: Benchmark):
        """
        Attempt to enforce a cold start for the next invocation of the given functions.

        The mechanism for this is provider-specific and may involve updating
        environment variables, redeploying, or other techniques.

        :param functions: A list of Function objects for which to enforce cold starts.
        :param code_package: The Benchmark object (may be used to pass unique values).
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
        Download provider-specific performance metrics for function invocations.

        This typically involves querying a logging or monitoring service (e.g., CloudWatch,
        Application Insights) for details like actual execution duration, memory usage, etc.,
        and populating the `requests` (ExecutionResult objects) and `metrics` dictionaries.

        :param function_name: The name of the function.
        :param start_time: The start timestamp of the time window for metric querying.
        :param end_time: The end timestamp of the time window.
        :param requests: Dictionary of request IDs to ExecutionResult objects to be updated.
        :param metrics: Dictionary to store any additional aggregated metrics.
        """
        pass

    @abstractmethod
    def create_trigger(self, function: Function, trigger_type: Trigger.TriggerType) -> Trigger:
        """
        Create a new trigger of a specific type for the given function.

        :param function: The Function object to which the trigger will be attached.
        :param trigger_type: The type of trigger to create (e.g., HTTP, STORAGE).
        :return: The created Trigger object.
        """
        pass

    def disable_rich_output(self):
        """
        Disable rich progress bar outputs, e.g., during Docker image pushes.
        Useful for environments where rich output is not supported or desired.
        """
        pass

    # @abstractmethod
    # def get_invocation_error(self, function_name: str,
    #   start_time: int, end_time: int):
    #    pass

    @abstractmethod
    def shutdown(self) -> None:
        """
        Clean up and shut down the FaaS system interface.

        This should release any acquired resources, stop any running local services
        (like Docker containers started by SeBS for CLI interactions), and update
        the cache with the final system configuration.
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
        Return the name of the FaaS provider (e.g., "aws", "azure", "gcp", "local").

        :return: The provider name string.
        """
        pass
