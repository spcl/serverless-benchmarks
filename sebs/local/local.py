import os
import requests
import shutil
import time
from typing import cast, Dict, List, Optional, Type, Tuple  # noqa
import subprocess
import socket

import docker

from sebs.cache import Cache
from sebs.config import SeBSConfig
from sebs.storage.resources import SelfHostedSystemResources
from sebs.utils import LoggingHandlers, is_linux
from sebs.local.config import LocalConfig
from sebs.local.function import LocalFunction
from sebs.faas.function import Function, FunctionConfig, ExecutionResult, Trigger
from sebs.faas.system import System
from sebs.faas.config import Resources
from sebs.benchmark import Benchmark


class Local(System):
    """
    Local FaaS system implementation.

    Manages functions running locally in Docker containers. It handles
    packaging code, starting/stopping containers, and creating triggers
    for local invocation.
    """
    DEFAULT_PORT = 9000

    @staticmethod
    def name() -> str:
        """Return the name of the FaaS system (local)."""
        return "local"

    @staticmethod
    def typename() -> str:
        """Return the type name of this FaaS system class."""
        return "Local"

    @staticmethod
    def function_type() -> "Type[Function]":
        """Return the type of the function implementation for local deployments."""
        return LocalFunction

    @property
    def config(self) -> LocalConfig:
        """Return the local-specific configuration."""
        return self._config

    @property
    def remove_containers(self) -> bool:
        """Flag indicating whether to remove containers after they are stopped."""
        return self._remove_containers

    @remove_containers.setter
    def remove_containers(self, val: bool):
        """Set the flag for removing containers after stopping."""
        self._remove_containers = val

    @property
    def measure_interval(self) -> int:
        """Interval in seconds for memory measurements, if enabled. -1 means disabled."""
        return self._measure_interval

    @property
    def measurements_enabled(self) -> bool:
        """Check if memory measurements are enabled."""
        return self._measure_interval > -1

    @property
    def measurement_path(self) -> Optional[str]:
        """Path to the file where memory measurements are stored, if enabled."""
        return self._memory_measurement_path

    def __init__(
        self,
        sebs_config: SeBSConfig,
        config: LocalConfig,
        cache_client: Cache,
        docker_client: docker.client,
        logger_handlers: LoggingHandlers,
    ):
        """
        Initialize the Local FaaS system.

        :param sebs_config: SeBS system configuration.
        :param config: Local-specific configuration.
        :param cache_client: Function cache instance.
        :param docker_client: Docker client instance.
        :param logger_handlers: Logging handlers.
        """
        super().__init__(
            sebs_config,
            cache_client,
            docker_client,
            SelfHostedSystemResources( # Uses SelfHosted for local storage/NoSQL
                "local", config, cache_client, docker_client, logger_handlers
            ),
        )
        self.logging_handlers = logger_handlers
        self._config = config
        self._remove_containers = True
        self._memory_measurement_path: Optional[str] = None
        self._measure_interval = -1 # Default: disabled

        self.initialize_resources(select_prefix="local") # Resource ID for local is "local"

    def shutdown(self):
        """
        Shut down the local FaaS system.
        Currently, this involves updating the cache via the parent class's shutdown.
        Local storage (Minio) or NoSQL (ScyllaDB) shutdown is handled by SelfHostedSystemResources.
        """
        super().shutdown()

    def package_code(
        self,
        directory: str,
        language_name: str,
        language_version: str,
        architecture: str, # architecture is not used for local Docker image selection yet
        benchmark: str,
        is_cached: bool, # is_cached is not directly used in local packaging logic
        container_deployment: bool, # container_deployment is not supported for local
    ) -> Tuple[str, int, str]:
        """
        Package benchmark code for local Docker deployment.

        The standard SeBS code directory structure is adapted:
        - Files not part of `CONFIG_FILES` are moved into a 'function' subdirectory.
        This prepares the `directory` to be mounted into the Docker container.
        No actual zipping or separate package creation occurs; the directory itself is used.

        The directory structure expected by the local runner (inside the container at /function):
        - handler.py / handler.js (at the root of the mount)
        - requirements.txt / package.json (at the root of the mount)
        - .python_packages / node_modules (at the root, created by benchmark build step)
        - function/ (subdirectory containing other benchmark source files and resources)

        :param directory: Path to the code directory.
        :param language_name: Programming language name.
        :param language_version: Programming language version.
        :param architecture: Target architecture (not directly used in local packaging).
        :param benchmark: Benchmark name.
        :param is_cached: Whether the code is cached (not directly used here).
        :param container_deployment: Whether to package for container deployment (not supported).
        :return: Tuple containing:
            - Path to the prepared code directory.
            - Size of the directory in bytes.
            - Empty string for container URI.
        """
        # Local deployment doesn't produce a separate package file or container URI here.
        # It prepares the directory for mounting.
        CONFIG_FILES = {
            "python": ["handler.py", "requirements.txt", ".python_packages"],
            "nodejs": ["handler.js", "package.json", "node_modules"],
        }
        package_config_exclusions = CONFIG_FILES[language_name]
        function_subdir = os.path.join(directory, "function")
        os.makedirs(function_subdir, exist_ok=True)

        # Move all files not in package_config_exclusions into the 'function' subdirectory
        for item_name in os.listdir(directory):
            if item_name not in package_config_exclusions and item_name != "function":
                source_item_path = os.path.join(directory, item_name)
                destination_item_path = os.path.join(function_subdir, item_name)
                # Ensure not to move the 'function' directory into itself if it already exists and has content
                if os.path.abspath(source_item_path) != os.path.abspath(function_subdir):
                    shutil.move(source_item_path, destination_item_path)
        
        # Calculate size of the directory to be mounted.
        # Benchmark.directory_size(directory) might be more accurate if it exists.
        # For now, using os.path.getsize on the root directory might not be correct for total size.
        # A more robust way would be to sum sizes of all files in the directory.
        # However, to match original behavior of just returning directory path:
        total_size = 0
        for path, dirs, files in os.walk(directory):
            for f in files:
                fp = os.path.join(path, f)
                total_size += os.path.getsize(fp)
        
        mbytes = total_size / 1024.0 / 1024.0
        self.logging.info(f"Prepared function directory at {directory}, size {mbytes:.2f} MB")

        return directory, total_size, ""


    def _start_container(
        self, code_package: Benchmark, func_name: str, func_obj: Optional[LocalFunction]
    ) -> LocalFunction:
        """
        Start a Docker container for the given benchmark code.

        Configures environment variables, mounts the code package, and sets up
        networking. If memory measurements are enabled, starts a subprocess to
        monitor the container's memory usage.

        :param code_package: The Benchmark object.
        :param func_name: The name for the function/container.
        :param func_obj: Optional existing LocalFunction object to reuse/update.
        :return: The LocalFunction instance associated with the started container.
        :raises RuntimeError: If a port cannot be allocated or the container fails to start.
        """
        container_image_name = "{}:run.local.{}.{}".format(
            self._system_config.docker_repository(),
            code_package.language_name,
            code_package.language_version,
        )

        environment_vars = {
            "CONTAINER_UID": str(os.getuid()) if hasattr(os, 'getuid') else '1000', # Default for non-Unix
            "CONTAINER_GID": str(os.getgid()) if hasattr(os, 'getgid') else '1000', # Default for non-Unix
            "CONTAINER_USER": self._system_config.username(self.name(), code_package.language_name),
        }
        if self.config.resources.storage_config:
            environment_vars.update(self.config.resources.storage_config.envs())

        if code_package.uses_nosql:
            nosql_storage = self.system_resources.get_nosql_storage()
            environment_vars.update(nosql_storage.envs())
            for original_name, actual_name in nosql_storage.get_tables(code_package.benchmark).items():
                environment_vars[f"NOSQL_STORAGE_TABLE_{original_name}"] = actual_name

        # Default container settings
        # FIXME: CPU, memory, timeout configurations are placeholders.
        container_kwargs: Dict[str, Any] = {
            "image": container_image_name,
            "volumes": {code_package.code_location: {"bind": "/function", "mode": "ro"}},
            "environment": environment_vars,
            "privileged": True, # Needed for some benchmarks or measurement tools
            "security_opt": ["seccomp:unconfined"], # For tools like perf
            "network_mode": "bridge",
            "remove": self.remove_containers,
            "stdout": True,
            "stderr": True,
            "detach": True,
        }

        # Port handling:
        # On Linux, container uses DEFAULT_PORT directly on its bridge IP.
        # On non-Linux (Docker Desktop), map a host port to container's DEFAULT_PORT.
        container_internal_port = self.DEFAULT_PORT
        host_mapped_port = container_internal_port # Default to same port for Linux bridge scenario

        if not is_linux(): # E.g., Docker Desktop on macOS/Windows
            allocated_host_port = None
            for p in range(self.DEFAULT_PORT, self.DEFAULT_PORT + 1000):
                if p not in self.config.resources.allocated_ports:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                        try:
                            s.bind(("127.0.0.1", p))
                            allocated_host_port = p
                            self.config.resources.allocated_ports.add(p)
                            break
                        except socket.error:
                            continue # Port in use on host
            if allocated_host_port is None:
                raise RuntimeError(
                    f"Failed to allocate host port: No ports available between "
                    f"{self.DEFAULT_PORT} and {self.DEFAULT_PORT + 999}"
                )
            host_mapped_port = allocated_host_port
            container_kwargs["ports"] = {f"{container_internal_port}/tcp": host_mapped_port}
        
        # Command to run inside the container, using the internal port
        container_kwargs["command"] = f"/bin/bash /sebs/run_server.sh {container_internal_port}"

        running_container = self._docker_client.containers.run(**container_kwargs)

        # Memory measurement process
        measurement_process_pid: Optional[int] = None
        if self.measurements_enabled and self._memory_measurement_path:
            proc = subprocess.Popen([
                "python3", "./sebs/local/measureMem.py",
                "--container-id", running_container.id,
                "--measure-interval", str(self.measure_interval),
                "--measurement-file", self._memory_measurement_path,
            ])
            measurement_process_pid = proc.pid

        # Create or update LocalFunction object
        if func_obj is None:
            function_config_obj = FunctionConfig.from_benchmark(code_package)
            func_obj = LocalFunction(
                running_container, host_mapped_port, func_name,
                code_package.benchmark, code_package.hash,
                function_config_obj, measurement_process_pid,
            )
        else:
            func_obj.container = running_container
            func_obj._measurement_pid = measurement_process_pid
            # func_obj._port might need update if host_mapped_port changed, though current logic reuses.

        # Wait for the server within the container to start
        max_retries = 10
        for attempt in range(max_retries):
            try:
                # Use func_obj.url which correctly points to localhost or container IP
                requests.get(f"http://{func_obj.url}/alive", timeout=1)
                self.logging.info(
                    f"Started {func_name} in container {running_container.id}, listening on {func_obj.url}"
                )
                return func_obj
            except requests.exceptions.ConnectionError:
                if attempt < max_retries - 1:
                    time.sleep(0.25)
                else:
                    raise RuntimeError(
                        f"Couldn't start {func_name} in container {running_container.id} "
                        f"(URL: {func_obj.url}). Server did not become alive."
                    )
        # Should not be reached if loop completes or raises
        return func_obj


    def create_function(
        self,
        code_package: Benchmark,
        func_name: str,
        container_deployment: bool, # Not used for Local
        container_uri: str, # Not used for Local
    ) -> "LocalFunction":
        """
        Create a new local function, which involves starting a Docker container.

        :param code_package: The Benchmark object containing code and configuration.
        :param func_name: The desired name for the function.
        :param container_deployment: Flag for container deployment (not supported/used for Local).
        :param container_uri: Container URI (not used for Local).
        :return: The created LocalFunction instance.
        :raises NotImplementedError: If container_deployment is True.
        """
        if container_deployment:
            raise NotImplementedError("Container deployment is not supported in Local")
        return self._start_container(code_package, func_name, None)

    def update_function(
        self,
        function: Function,
        code_package: Benchmark,
        container_deployment: bool, # Not used for Local
        container_uri: str, # Not used for Local
    ):
        """
        Update an existing local function. This typically involves stopping the old
        Docker container and starting a new one with the updated code or configuration.

        :param function: The existing LocalFunction object to update.
        :param code_package: Benchmark object with the new code/configuration.
        :param container_deployment: Flag for container deployment (not used).
        :param container_uri: Container URI (not used).
        """
        local_func = cast(LocalFunction, function)
        local_func.stop() # Stop the old container
        self.logging.info("Allocating a new function container with updated code.")
        # _start_container will create a new container and update func_obj if provided
        self._start_container(code_package, local_func.name, local_func)

    def create_trigger(self, func: Function, trigger_type: Trigger.TriggerType) -> Trigger:
        """
        Create a trigger for a local function.
        For local deployments, only HTTP triggers are typically relevant and are
        derived from the function's container URL.

        :param func: The LocalFunction object.
        :param trigger_type: The type of trigger to create (must be HTTP).
        :return: The created HTTPTrigger object.
        :raises RuntimeError: If a non-HTTP trigger type is requested.
        """
        from sebs.local.function import HTTPTrigger # Local import

        local_function = cast(LocalFunction, func)
        if trigger_type == Trigger.TriggerType.HTTP:
            # The URL is determined when LocalFunction is initialized or container restarts
            http_trigger = HTTPTrigger(local_function.url)
            http_trigger.logging_handlers = self.logging_handlers # Ensure handlers are set
        else:
            raise RuntimeError(f"Trigger type {trigger_type.value} not supported for Local deployment!")

        local_function.add_trigger(http_trigger)
        self.cache_client.update_function(local_function) # Update cache with new trigger info
        return http_trigger

    def cached_function(self, function: Function):
        """
        Perform setup for a cached LocalFunction instance.
        Currently, no specific actions are needed for local cached functions beyond
        what's done during deserialization (e.g., re-attaching to Docker container).
        Ensures HTTP trigger has the correct URL if function was re-instantiated.

        :param function: The LocalFunction object retrieved from cache.
        """
        local_func = cast(LocalFunction, function)
        # Ensure HTTP trigger URL is up-to-date, especially if container IP changed (though less likely for local)
        http_triggers = local_func.triggers(Trigger.TriggerType.HTTP)
        if http_triggers:
            cast(HTTPTrigger, http_triggers[0]).url = local_func.url
        elif not http_triggers: # If no HTTP trigger, create one
            self.create_trigger(local_func, Trigger.TriggerType.HTTP)


    def update_function_configuration(self, function: Function, code_package: Benchmark):
        """
        Update function configuration for a local deployment.
        Note: This is not supported for local deployments as configuration changes
        typically require restarting the container with new settings, which is
        handled by `update_function`.

        :param function: The function to configure.
        :param code_package: Benchmark with new configuration.
        :raises RuntimeError: Always, as this operation is not supported.
        """
        self.logging.error("Updating function configuration of local deployment is not supported")
        raise RuntimeError("Updating function configuration of local deployment is not supported")

    def download_metrics(
        self,
        function_name: str, # Not directly used, metrics are tied to container IDs or local files
        start_time: int, # Not directly used for local memory metrics
        end_time: int, # Not directly used for local memory metrics
        requests: Dict[str, ExecutionResult], # Not directly used for local memory metrics
        metrics: dict, # Not directly used for local memory metrics
    ):
        """
        Download/process metrics for local functions.
        For local deployments, this typically refers to processing memory measurement
        files if enabled. Other provider-specific metrics (like billing) are not applicable.

        :param function_name: Name of the function (for context, not direct query).
        :param start_time: Start time for metrics window (not used for local memory).
        :param end_time: End time for metrics window (not used for local memory).
        :param requests: Dictionary of request IDs to ExecutionResult objects.
        :param metrics: Dictionary to store any additional metrics.
        """
        # Local memory metrics are processed during `deployment.shutdown()`.
        # No cloud provider metrics to download.
        self.logging.info("Local deployment: Metrics (memory) processed during deployment shutdown.")
        pass

    def enforce_cold_start(self, functions: List[Function], code_package: Benchmark):
        """
        Enforce a cold start for local functions.
        This typically means stopping and restarting the Docker container(s).

        :param functions: List of LocalFunction objects.
        :param code_package: The Benchmark object.
        :raises NotImplementedError: This method is not fully implemented in a way that
                                     guarantees a "cold start" equivalent beyond container restart.
        """
        # For local, a "cold start" means restarting the container.
        # This is effectively what update_function does.
        # A more direct way would be func.stop() then self._start_container(code_package, func.name, func)
        self.logging.warning("Enforcing cold start for local functions by restarting containers.")
        for func in functions:
            if isinstance(func, LocalFunction):
                self.update_function(func, code_package, False, "")
            else:
                self.logging.error(f"Cannot enforce cold start on non-LocalFunction: {func.name}")
        # The concept of a "cold start counter" doesn't directly apply to local in the same way
        # as cloud, where it might change env vars to force new instance versions.
        # Here, restart is the primary mechanism.

    @staticmethod
    def default_function_name(
        code_package: Benchmark, resources: Optional[Resources] = None
    ) -> str:
        """
        Generate a default name for a local function (container).

        If resources (and thus a resource_id) are provided, it includes the resource_id.
        Otherwise, it's based on benchmark name, language, and version.

        :param code_package: The Benchmark object.
        :param resources: Optional Resources object.
        :return: The generated default function name.
        """
        if resources and resources.has_resources_id: # Check if resources_id is available
            func_name = "sebs-{}-{}-{}-{}".format(
                resources.resources_id,
                code_package.benchmark,
                code_package.language_name,
                code_package.language_version,
            )
        else: # Fallback if no resources or no resource_id
            func_name = "sebs-{}-{}-{}".format( # Changed from sebd-
                code_package.benchmark,
                code_package.language_name,
                code_package.language_version,
            )
        return func_name

    @staticmethod
    def format_function_name(func_name: str) -> str:
        """
        Format the function name for local deployment.
        Currently, no specific formatting is applied.

        :param func_name: The original function name.
        :return: The formatted function name (same as input).
        """
        return func_name

    def start_measurements(self, measure_interval: int) -> Optional[str]:
        """
        Start memory measurements for local containers.

        Sets the measurement interval and creates a temporary file for storing
        measurement data collected by `measureMem.py`.

        :param measure_interval: Interval in seconds for taking memory measurements.
                                 If <= 0, measurements are disabled.
        :return: Path to the temporary measurement file if enabled, else None.
        """
        self._measure_interval = measure_interval

        if not self.measurements_enabled:
            self._memory_measurement_path = None
            return None

        # initialize an empty file for measurements to be written to
        import tempfile
        from pathlib import Path

        fd, temp_file_path = tempfile.mkstemp(suffix=".txt", prefix="sebs_mem_")
        self._memory_measurement_path = temp_file_path
        Path(self._memory_measurement_path).touch()
        os.close(fd) # Close the file descriptor opened by mkstemp

        self.logging.info(f"Memory measurements will be stored in {self._memory_measurement_path}")
        return self._memory_measurement_path
