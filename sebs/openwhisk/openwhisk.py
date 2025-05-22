import os
import subprocess
from typing import cast, Dict, List, Optional, Tuple, Type

import docker

from sebs.benchmark import Benchmark
from sebs.cache import Cache
from sebs.faas import System
from sebs.faas.function import Function, ExecutionResult, Trigger
from sebs.openwhisk.container import OpenWhiskContainer
from sebs.openwhisk.triggers import LibraryTrigger, HTTPTrigger
from sebs.storage.resources import SelfHostedSystemResources
from sebs.storage.minio import Minio
from sebs.storage.scylladb import ScyllaDB
from sebs.gcp.function import GCPFunction # This import seems incorrect for OpenWhisk module
from sebs.utils import LoggingHandlers
from sebs.faas.config import Resources
from .config import OpenWhiskConfig
from .function import OpenWhiskFunction, OpenWhiskFunctionConfig
from ..config import SeBSConfig # Relative import for SeBSConfig


"""
Apache OpenWhisk FaaS system implementation.

This class provides the SeBS interface for interacting with an OpenWhisk deployment,
including action (function) deployment, invocation, resource management (primarily
self-hosted storage like Minio/ScyllaDB via SelfHostedSystemResources), and
interaction with the `wsk` CLI.
"""


class OpenWhisk(System):
    """
    Apache OpenWhisk FaaS system implementation.

    Manages actions (functions) and related resources on an OpenWhisk deployment.
    Uses `wsk` CLI for deployment and management operations.
    """
    _config: OpenWhiskConfig

    def __init__(
        self,
        system_config: SeBSConfig,
        config: OpenWhiskConfig,
        cache_client: Cache,
        docker_client: docker.client,
        logger_handlers: LoggingHandlers,
    ):
        """
        Initialize OpenWhisk FaaS system.

        Sets up OpenWhisk-specific configurations, container client for Docker image
        management (if custom images are used), and logs into the Docker registry
        if credentials are provided.

        :param system_config: SeBS system configuration.
        :param config: OpenWhisk-specific configuration.
        :param cache_client: Function cache instance.
        :param docker_client: Docker client instance.
        :param logger_handlers: Logging handlers.
        """
        super().__init__(
            system_config,
            cache_client,
            docker_client,
            SelfHostedSystemResources( # OpenWhisk uses self-hosted resources for storage/NoSQL
                "openwhisk", config, cache_client, docker_client, logger_handlers
            ),
        )
        self._config = config
        self.logging_handlers = logger_handlers

        self.container_client = OpenWhiskContainer(
            self.system_config, self.config, self.docker_client, self.config.experimentalManifest
        )

        # Login to Docker registry if credentials are configured
        if self.config.resources.docker_username and self.config.resources.docker_password:
            registry_url = self.config.resources.docker_registry
            try:
                if registry_url:
                    docker_client.login(
                        username=self.config.resources.docker_username,
                        password=self.config.resources.docker_password,
                        registry=registry_url,
                    )
                    self.logging.info(f"Logged into Docker registry at {registry_url}")
                else: # Default to Docker Hub
                    docker_client.login(
                        username=self.config.resources.docker_username,
                        password=self.config.resources.docker_password,
                    )
                    self.logging.info("Logged into Docker Hub")
            except docker.errors.APIError as e:
                self.logging.error(f"Docker login failed: {e}")
                # Depending on policy, might raise error or continue without push capability

    def initialize(self, config: Dict[str, str] = {}, resource_prefix: Optional[str] = None):
        """
        Initialize OpenWhisk resources.

        Calls the base class method to initialize resources, which for OpenWhisk
        primarily involves setting up self-hosted storage if configured.

        :param config: System-specific parameters (not used by OpenWhisk).
        :param resource_prefix: Optional prefix for naming/selecting resources.
        """
        self.initialize_resources(select_prefix=resource_prefix)

    @property
    def config(self) -> OpenWhiskConfig:
        """Return the OpenWhisk-specific configuration."""
        return self._config

    def shutdown(self) -> None:
        """
        Shut down the OpenWhisk system interface.

        Stops self-hosted storage (Minio) if `shutdownStorage` is configured.
        Optionally removes the OpenWhisk cluster if `removeCluster` is configured
        (uses external tools). Updates the cache.
        """
        # Check if storage attribute exists and if shutdownStorage is true
        if hasattr(self._system_resources, "get_storage"): # Check if storage system is initialized
             storage_instance = self._system_resources.get_storage()
             if isinstance(storage_instance, Minio) and self.config.shutdownStorage:
                 self.logging.info("Stopping Minio storage for OpenWhisk.")
                 storage_instance.stop()
        # Similar check for NoSQL if OpenWhisk uses it and has a stop method
        # if hasattr(self._system_resources, "get_nosql_storage"):
        #    nosql_instance = self._system_resources.get_nosql_storage()
        #    if isinstance(nosql_instance, ScyllaDB) and self.config.shutdownNoSQLStorage: # Hypothetical
        #        nosql_instance.stop()

        if self.config.removeCluster:
            self.logging.info("Attempting to remove OpenWhisk cluster.")
            from tools.openwhisk_preparation import delete_cluster  # type: ignore
            try:
                delete_cluster()
                self.logging.info("OpenWhisk cluster removal process initiated.")
            except Exception as e:
                self.logging.error(f"Error during OpenWhisk cluster removal: {e}")
        super().shutdown()

    @staticmethod
    def name() -> str:
        """Return the name of the cloud provider (openwhisk)."""
        return "openwhisk"

    @staticmethod
    def typename() -> str: # Corrected from just typename()
        """Return the type name of the cloud provider (OpenWhisk)."""
        return "OpenWhisk"

    @staticmethod
    def function_type() -> "Type[Function]":
        """Return the type of the function implementation for OpenWhisk."""
        return OpenWhiskFunction

    def get_wsk_cmd(self) -> List[str]:
        """
        Construct the base command list for `wsk` CLI interactions.

        Includes the path to `wsk` executable and bypass security flag if configured.

        :return: List of command arguments for `wsk`.
        """
        cmd = [self.config.wsk_exec]
        if self.config.wsk_bypass_security:
            cmd.append("-i") # Bypass certificate checking
        return cmd

    def package_code(
        self,
        directory: str,
        language_name: str,
        language_version: str, # Not directly used by OpenWhisk packaging itself, but by image naming
        architecture: str, # Used for Docker image naming
        benchmark: str,
        is_cached: bool, # Used for Docker image building logic
        container_deployment: bool, # OpenWhisk primarily uses container deployments
    ) -> Tuple[str, int, str]:
        """
        Package benchmark code for OpenWhisk.

        Builds a Docker base image for the function if not already cached and available.
        Then, creates a zip file containing only the main handler (`__main__.py` or `index.js`)
        as required by OpenWhisk for action creation when using custom Docker images.
        The Docker image URI is returned, which will be used when creating the action.

        :param directory: Path to the benchmark code directory.
        :param language_name: Programming language name.
        :param language_version: Programming language version.
        :param architecture: Target CPU architecture for the Docker image.
        :param benchmark: Benchmark name.
        :param is_cached: Whether the Docker image is considered cached.
        :param container_deployment: Must be True for OpenWhisk custom runtimes.
        :return: Tuple containing:
            - Path to the created zip file (containing only the handler).
            - Size of the zip file in bytes.
            - Docker image URI for the function.
        :raises ValueError: If container_deployment is False (not typical for SeBS OpenWhisk).
        """
        if not container_deployment:
            # OpenWhisk with SeBS typically relies on custom Docker images for runtimes.
            # While OpenWhisk supports non-Docker actions, SeBS is geared towards Docker for consistency.
            self.logging.warning("Non-container deployment requested for OpenWhisk, this is unusual for SeBS.")
            # Proceeding, but the action creation might need a different --kind parameter.

        # Build or ensure Docker image for the action's runtime
        _, image_uri = self.container_client.build_base_image(
            directory, language_name, language_version, architecture, benchmark, is_cached
        )

        # OpenWhisk requires a zip file for the action, even if using a custom Docker image.
        # This zip should contain the main executable file.
        HANDLER_FILES = {
            "python": "__main__.py", # OpenWhisk Python convention
            "nodejs": "index.js",   # OpenWhisk Node.js convention
        }
        handler_file = HANDLER_FILES[language_name]

        # Create a zip containing only the handler file.
        # The actual benchmark code and dependencies are in the Docker image.
        benchmark_archive_path = os.path.join(directory, f"{benchmark}_action.zip")
        with zipfile.ZipFile(benchmark_archive_path, "w") as zf:
            handler_path_in_benchmark_dir = os.path.join(directory, handler_file)
            if os.path.exists(handler_path_in_benchmark_dir):
                zf.write(handler_path_in_benchmark_dir, arcname=handler_file)
            else:
                # This case should not happen if benchmark template is correct.
                # Create an empty file if handler is missing, though action would fail.
                self.logging.warning(f"Handler file {handler_file} not found in {directory}. Creating empty zip entry.")
                zf.writestr(handler_file, "")


        self.logging.info(f"Created action zip {benchmark_archive_path}")
        bytes_size = os.path.getsize(benchmark_archive_path)
        self.logging.info(f"Action zip archive size {bytes_size / 1024.0 / 1024.0:.2f} MB")
        
        return benchmark_archive_path, bytes_size, image_uri


    def storage_arguments(self, code_package: Benchmark) -> List[str]:
        """
        Generate `wsk action create/update` parameters for self-hosted storage.

        Constructs a list of `-p KEY VALUE` arguments for Minio and ScyllaDB
        connection details if they are configured and used by the benchmark.

        :param code_package: The Benchmark object.
        :return: List of string arguments for `wsk` CLI.
        """
        params = [] # Changed name from envs to params for clarity, as these are -p args

        if self.config.resources.storage_config:
            storage_envs = self.config.resources.storage_config.envs()
            params.extend([
                "-p", "MINIO_STORAGE_SECRET_KEY", storage_envs["MINIO_SECRET_KEY"],
                "-p", "MINIO_STORAGE_ACCESS_KEY", storage_envs["MINIO_ACCESS_KEY"],
                "-p", "MINIO_STORAGE_CONNECTION_URL", storage_envs["MINIO_ADDRESS"],
            ])

        if code_package.uses_nosql:
            nosql_storage = self.system_resources.get_nosql_storage()
            for key, value in nosql_storage.envs().items():
                params.extend(["-p", key, value])
            for original_name, actual_name in nosql_storage.get_tables(code_package.benchmark).items():
                params.extend(["-p", f"NOSQL_STORAGE_TABLE_{original_name}", actual_name])
        return params

    def create_function(
        self,
        code_package: Benchmark,
        func_name: str,
        container_deployment: bool, # Should be True for OpenWhisk with SeBS
        container_uri: str, # Docker image URI from package_code
    ) -> "OpenWhiskFunction":
        """
        Create or update an OpenWhisk action.

        Checks if an action with the given name already exists. If so, it updates it.
        Otherwise, a new action is created using the provided Docker image URI and
        other benchmark configurations (memory, timeout, storage parameters).

        :param code_package: Benchmark object with code and configuration.
        :param func_name: Desired name for the action.
        :param container_deployment: Flag for container deployment (expected to be True).
        :param container_uri: Docker image URI for the action's runtime.
        :return: OpenWhiskFunction object.
        :raises RuntimeError: If `wsk` CLI command fails or is not found.
        """
        self.logging.info(f"Creating OpenWhisk action {func_name} using image {container_uri}.")
        try:
            # Check if action already exists
            list_cmd = [*self.get_wsk_cmd(), "action", "list"]
            actions_list_process = subprocess.run(list_cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            if actions_list_process.returncode != 0:
                self.logging.error(f"Failed to list actions: {actions_list_process.stderr}")
                raise RuntimeError("wsk action list command failed.")

            function_found = any(func_name in line.split(None, 1)[0] for line in actions_list_process.stdout.splitlines() if line)
            
            function_config = OpenWhiskFunctionConfig.from_benchmark(code_package)
            if self.config.resources.storage_config: # If Minio is configured
                function_config.object_storage = cast(Minio, self.system_resources.get_storage()).config
            if code_package.uses_nosql and self.config.resources.nosql_storage_config: # If ScyllaDB is configured
                function_config.nosql_storage = cast(ScyllaDB, self.system_resources.get_nosql_storage()).config
            function_config.docker_image = container_uri # Store the image used

            openwhisk_func = OpenWhiskFunction(func_name, code_package.benchmark, code_package.hash, function_config)

            if function_found:
                self.logging.info(f"Action {func_name} already exists, updating it.")
                self.update_function(openwhisk_func, code_package, container_deployment, container_uri)
            else:
                self.logging.info(f"Creating new OpenWhisk action {func_name}.")
                action_cmd = [
                    *self.get_wsk_cmd(), "action", "create", func_name,
                    "--web", "true", # Make it a web action for HTTP trigger
                    "--docker", container_uri,
                    "--memory", str(code_package.benchmark_config.memory),
                    "--timeout", str(code_package.benchmark_config.timeout * 1000), # OpenWhisk timeout is in ms
                    *self.storage_arguments(code_package),
                    code_package.code_location, # Path to the small zip file
                ]
                try:
                    subprocess.run(action_cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, check=True, text=True)
                except subprocess.CalledProcessError as e:
                    self.logging.error(f"Cannot create action {func_name}: {e.stderr}")
                    raise RuntimeError(e)
        
        except FileNotFoundError: # wsk executable not found
            self.logging.error(f"wsk CLI not found at {self.config.wsk_exec}. Please ensure it's installed and in PATH or configured correctly.")
            raise RuntimeError("wsk CLI not found.")

        # Add default LibraryTrigger
        library_trigger = LibraryTrigger(func_name, self.get_wsk_cmd())
        library_trigger.logging_handlers = self.logging_handlers
        openwhisk_func.add_trigger(library_trigger)
        
        # HTTP trigger is created by --web true, now associate it in SeBS
        self.create_trigger(openwhisk_func, Trigger.TriggerType.HTTP)

        return openwhisk_func

    def update_function(
        self,
        function: Function,
        code_package: Benchmark,
        container_deployment: bool, # Expected to be True
        container_uri: str, # New Docker image URI
    ):
        """
        Update an existing OpenWhisk action.

        Uses `wsk action update` with the new Docker image URI, code package (zip),
        and configuration parameters.

        :param function: The OpenWhiskFunction object to update.
        :param code_package: Benchmark object with new code and configuration.
        :param container_deployment: Flag for container deployment.
        :param container_uri: New Docker image URI.
        :raises RuntimeError: If `wsk` CLI command fails or is not found.
        """
        self.logging.info(f"Updating existing OpenWhisk action {function.name} with image {container_uri}.")
        openwhisk_func = cast(OpenWhiskFunction, function)
        
        # Update function configuration from benchmark, as it might have changed
        new_config = OpenWhiskFunctionConfig.from_benchmark(code_package)
        if self.config.resources.storage_config:
            new_config.object_storage = cast(Minio, self.system_resources.get_storage()).config
        if code_package.uses_nosql and self.config.resources.nosql_storage_config:
            new_config.nosql_storage = cast(ScyllaDB, self.system_resources.get_nosql_storage()).config
        new_config.docker_image = container_uri
        openwhisk_func._cfg = new_config # Update the function's internal config

        action_cmd = [
            *self.get_wsk_cmd(), "action", "update", function.name,
            "--web", "true",
            "--docker", container_uri,
            "--memory", str(code_package.benchmark_config.memory),
            "--timeout", str(code_package.benchmark_config.timeout * 1000),
            *self.storage_arguments(code_package),
            code_package.code_location, # Path to the action's zip file
        ]
        try:
            subprocess.run(action_cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, check=True, text=True)
            openwhisk_func.config.docker_image = container_uri # Ensure config reflects the new image
        except FileNotFoundError as e:
            self.logging.error(f"wsk CLI not found at {self.config.wsk_exec} during update.")
            raise RuntimeError(e)
        except subprocess.CalledProcessError as e:
            self.logging.error(f"Error updating action {function.name}: {e.stderr}")
            self.logging.error("Consider removing SeBS cache (.sebs.cache) if issues persist after OpenWhisk restart.")
            raise RuntimeError(e)

    def update_function_configuration(self, function: Function, code_package: Benchmark):
        """
        Update the configuration (memory, timeout, parameters) of an existing OpenWhisk action.
        This does not update the action's code or Docker image.

        :param function: The OpenWhiskFunction object whose configuration is to be updated.
        :param code_package: Benchmark object providing the new configuration values.
        :raises RuntimeError: If `wsk` CLI command fails or is not found.
        """
        self.logging.info(f"Updating configuration of OpenWhisk action {function.name}.")
        # Update the function's internal config object first
        function_cfg = cast(OpenWhiskFunctionConfig, function.config)
        function_cfg.memory = code_package.benchmark_config.memory
        function_cfg.timeout = code_package.benchmark_config.timeout
        # Re-evaluate storage arguments as they might depend on benchmark config
        storage_args = self.storage_arguments(code_package)

        action_cmd = [
            *self.get_wsk_cmd(), "action", "update", function.name,
            "--memory", str(function_cfg.memory),
            "--timeout", str(function_cfg.timeout * 1000),
            *storage_args
        ]
        try:
            subprocess.run(action_cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, check=True, text=True)
        except FileNotFoundError as e:
            self.logging.error(f"wsk CLI not found at {self.config.wsk_exec} during config update.")
            raise RuntimeError(e)
        except subprocess.CalledProcessError as e:
            self.logging.error(f"Error updating action configuration for {function.name}: {e.stderr}")
            raise RuntimeError(e)

    def is_configuration_changed(self, cached_function: Function, benchmark: Benchmark) -> bool:
        """
        Check if the function's configuration has changed compared to the benchmark.

        Compares memory, timeout, and storage configurations.

        :param cached_function: The cached OpenWhiskFunction object.
        :param benchmark: The Benchmark object with current settings.
        :return: True if configuration has changed, False otherwise.
        """
        changed = super().is_configuration_changed(cached_function, benchmark)
        openwhisk_func = cast(OpenWhiskFunction, cached_function)

        # Check object storage config
        if self.config.resources.storage_config:
            current_minio_config = cast(Minio, self.system_resources.get_storage()).config
            if openwhisk_func.config.object_storage != current_minio_config:
                self.logging.info("Object storage configuration changed.")
                changed = True
                openwhisk_func.config.object_storage = current_minio_config
        elif openwhisk_func.config.object_storage is not None: # Was configured, now it's not
            self.logging.info("Object storage configuration removed.")
            changed = True
            openwhisk_func.config.object_storage = None
            
        # Check NoSQL storage config
        if benchmark.uses_nosql and self.config.resources.nosql_storage_config:
            current_nosql_config = cast(ScyllaDB, self.system_resources.get_nosql_storage()).config
            if openwhisk_func.config.nosql_storage != current_nosql_config:
                self.logging.info("NoSQL storage configuration changed.")
                changed = True
                openwhisk_func.config.nosql_storage = current_nosql_config
        elif openwhisk_func.config.nosql_storage is not None: # Was configured, now it's not (or benchmark no longer uses nosql)
             self.logging.info("NoSQL storage configuration removed or benchmark no longer uses NoSQL.")
             changed = True
             openwhisk_func.config.nosql_storage = None
        return changed

    def default_function_name(
        self, code_package: Benchmark, resources: Optional[Resources] = None
    ) -> str:
        """
        Generate a default name for an OpenWhisk action.

        The name includes SeBS prefix, resource ID, benchmark name, language, and version.

        :param code_package: The Benchmark object.
        :param resources: Optional Resources object (uses self.config.resources if None).
        :return: The generated default action name.
        """
        # Use self.config.resources if resources parameter is None
        current_resources = resources if resources else self.config.resources
        return (
            f"sebs-{current_resources.resources_id}-{code_package.benchmark}-"
            f"{code_package.language_name}-{code_package.language_version}"
        )

    def enforce_cold_start(self, functions: List[Function], code_package: Benchmark):
        """
        Enforce a cold start for OpenWhisk actions.
        Note: True cold start enforcement is challenging in OpenWhisk without
        administrative control over the cluster or specific runtime behaviors.
        This method is currently not implemented.

        :param functions: List of functions.
        :param code_package: Benchmark object.
        :raises NotImplementedError: This feature is not implemented.
        """
        raise NotImplementedError("Cold start enforcement is not implemented for OpenWhisk.")

    def download_metrics(
        self,
        function_name: str,
        start_time: int,
        end_time: int,
        requests: Dict[str, ExecutionResult],
        metrics: dict,
    ):
        """
        Download metrics for OpenWhisk actions.
        OpenWhisk standardly provides some metrics in activation records.
        This method could be extended to parse `wsk activation logs` or use
        OpenWhisk monitoring APIs if available and configured.
        Currently, it's a placeholder.

        :param function_name: Name of the action.
        :param start_time: Start timestamp for querying metrics.
        :param end_time: End timestamp for querying metrics.
        :param requests: Dictionary of request IDs to ExecutionResult objects.
        :param metrics: Dictionary to store additional metrics.
        """
        # Metrics like execution time, init time are often part of activation record.
        # SeBS's OpenWhisk LibraryTrigger already parses some of this from invocation result.
        # This method could be used for more detailed/batch metric collection if needed.
        self.logging.info(f"Metrics download for OpenWhisk function {function_name} requested but not fully implemented beyond activation record parsing.")
        pass

    def create_trigger(self, function: Function, trigger_type: Trigger.TriggerType) -> Trigger:
        """
        Create a trigger for an OpenWhisk action.

        Supports Library triggers (default, created with function) and HTTP triggers
        (retrieves the web action URL).

        :param function: The OpenWhiskFunction object.
        :param trigger_type: The type of trigger to create.
        :return: The created Trigger object.
        :raises RuntimeError: If `wsk` CLI fails or an unsupported trigger type is requested.
        """
        if trigger_type == Trigger.TriggerType.LIBRARY:
            # Library triggers are usually created and associated during function creation.
            # Return existing one if found, otherwise log warning.
            existing_triggers = function.triggers(Trigger.TriggerType.LIBRARY)
            if existing_triggers:
                return existing_triggers[0]
            else:
                self.logging.warning(f"LibraryTrigger requested for {function.name} but not found. One should be added during function creation.")
                # Fallback: attempt to create and add one, though this might indicate an issue in the creation flow.
                lib_trigger = LibraryTrigger(function.name, self.get_wsk_cmd())
                lib_trigger.logging_handlers = self.logging_handlers
                function.add_trigger(lib_trigger)
                self.cache_client.update_function(function)
                return lib_trigger

        elif trigger_type == Trigger.TriggerType.HTTP:
            try:
                action_get_cmd = [*self.get_wsk_cmd(), "action", "get", function.name, "--url"]
                response = subprocess.run(action_get_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, text=True)
            except FileNotFoundError:
                self.logging.error(f"wsk CLI not found at {self.config.wsk_exec} when creating HTTP trigger.")
                raise RuntimeError("wsk CLI not found.")
            except subprocess.CalledProcessError as e:
                self.logging.error(f"Failed to get URL for action {function.name}: {e.stderr}")
                raise RuntimeError(f"Failed to get action URL: {e.stderr}")
            
            # Output of `wsk action get --url` is typically "ok: got action X, URL: https://..."
            # Need to parse the URL carefully.
            url_line = response.stdout.strip().split("\n")[-1] # Get the last line which should contain the URL
            if "https://" in url_line:
                # A common format is "ok: got action function_name, web action via https://..."
                # Or directly "https://..."
                url = url_line.split("https://")[-1]
                if not url.startswith("https://"):
                    url = "https://" + url
                # OpenWhisk web actions often append .json or similar for content type negotiation,
                # but the base URL is what's needed. SeBS HTTP client handles adding .json if required by endpoint.
                # However, `wsk action get --url` usually gives the direct invokable URL.
                # The original code added ".json", which might be specific to how their actions were written
                # or how they expected to call them. For generic web actions, this might not be needed.
                # Let's keep it for now to match old behavior.
                if not url.endswith(".json"):
                     url += ".json" 
                http_trigger = HTTPTrigger(function.name, url) # HTTPTrigger constructor might need adjustment if it takes name
                http_trigger.logging_handlers = self.logging_handlers
                function.add_trigger(http_trigger)
                self.cache_client.update_function(function)
                return http_trigger
            else:
                raise RuntimeError(f"Could not parse HTTP trigger URL from wsk output: {response.stdout}")
        else:
            raise RuntimeError(f"Unsupported trigger type {trigger_type.value} for OpenWhisk.")


    def cached_function(self, function: Function):
        """
        Configure a cached OpenWhiskFunction instance.

        Sets up logging handlers for its library and HTTP triggers and ensures
        the `wsk` command is set for library triggers.

        :param function: The OpenWhiskFunction object retrieved from cache.
        """
        for trigger in function.triggers(Trigger.TriggerType.LIBRARY):
            trigger.logging_handlers = self.logging_handlers
            cast(LibraryTrigger, trigger).wsk_cmd = self.get_wsk_cmd()
        for trigger in function.triggers(Trigger.TriggerType.HTTP):
            trigger.logging_handlers = self.logging_handlers
            # HTTPTrigger URL should be correct from deserialization if it was stored.
            # If not, it might need re-fetching if function was just deserialized without full context.
            # However, create_trigger is usually called to establish it.

    def disable_rich_output(self):
        """Disable rich progress bar output for the container client (Docker operations)."""
        self.container_client.disable_rich_output = True
