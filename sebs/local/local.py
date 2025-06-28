"""Local execution platform for SeBS.

It runs serverless functions locally using Docker containers, providing a
development and testing environment that mimics serverless execution without requiring
cloud platform deployment.

The local platform provides:
- Docker-based function execution
- HTTP triggers for function invocation
- Memory profiling and measurement capabilities
- Port management for multiple concurrent functions
- Cross-platform support (Linux, macOS, Windows)

Key Classes:
    Local: Main system class implementing the local execution platform
"""

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
    """Local execution platform implementation.

    Attributes:
        DEFAULT_PORT: Default port number for function containers (9000)
        _config: Local platform configuration
        _remove_containers: Whether to automatically remove containers after use
        _memory_measurement_path: Path to memory measurement file
        _measure_interval: Interval for memory measurements (-1 disables)
    """

    DEFAULT_PORT = 9000

    @staticmethod
    def name() -> str:
        """Get the platform name.

        Returns:
            str: Platform name "local"
        """
        return "local"

    @staticmethod
    def typename() -> str:
        """Get the platform type name.

        Returns:
            str: Type name "Local"
        """
        return "Local"

    @staticmethod
    def function_type() -> "Type[Function]":
        """Get the function type for this platform.

        Returns:
            Type[Function]: LocalFunction class
        """
        return LocalFunction

    @property
    def config(self) -> LocalConfig:
        """Get the local platform configuration.

        Returns:
            LocalConfig: The platform configuration
        """
        return self._config

    @property
    def remove_containers(self) -> bool:
        """Get whether containers are automatically removed.

        Returns:
            bool: True if containers are removed after use
        """
        return self._remove_containers

    @remove_containers.setter
    def remove_containers(self, val: bool) -> None:
        """Set whether containers are automatically removed.

        Args:
            val: Whether to remove containers after use
        """
        self._remove_containers = val

    @property
    def measure_interval(self) -> int:
        """Get the memory measurement interval.

        Returns:
            int: Measurement interval in milliseconds, -1 if disabled
        """
        return self._measure_interval

    @property
    def measurements_enabled(self) -> bool:
        """Check if memory measurements are enabled.

        Returns:
            bool: True if measurements are enabled
        """
        return self._measure_interval > -1

    @property
    def measurement_path(self) -> Optional[str]:
        """Get the path to the memory measurement file.

        Returns:
            Optional[str]: Path to measurement file, or None if not set
        """
        return self._memory_measurement_path

    def __init__(
        self,
        sebs_config: SeBSConfig,
        config: LocalConfig,
        cache_client: Cache,
        docker_client: docker.client,
        logger_handlers: LoggingHandlers,
    ):
        """Initialize the local execution platform.

        Args:
            sebs_config: Global SeBS configuration
            config: Local platform configuration
            cache_client: Cache client for storing artifacts
            docker_client: Docker client for container management
            logger_handlers: Logging handlers for output
        """
        super().__init__(
            sebs_config,
            cache_client,
            docker_client,
            SelfHostedSystemResources(
                "local", config, cache_client, docker_client, logger_handlers
            ),
        )
        self.logging_handlers = logger_handlers
        self._config = config
        self._remove_containers = True
        self._memory_measurement_path: Optional[str] = None
        # disable external measurements
        self._measure_interval = -1

        self.initialize_resources(select_prefix="local")

    def shutdown(self) -> None:
        """Shut down the local platform.

        Performs cleanup operations including shutting down any storage instances.
        """
        super().shutdown()

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
        """Package function code for local execution.

        Creates a compatible code package structure for local execution that
        maintains compatibility across cloud providers. Reorganizes files into
        a module structure to handle relative imports properly.

        The packaging creates this structure:
        - function/
          - function.py
          - storage.py
          - resources/
        - handler.py

        Args:
            directory: Directory containing the function code
            language_name: Programming language (e.g., "python", "nodejs")
            language_version: Language version (e.g., "3.8", "14")
            architecture: Target architecture (unused for local)
            benchmark: Benchmark name
            is_cached: Whether the package is from cache
            container_deployment: Whether using container deployment

        Returns:
            Tuple[str, int, str]: (package_path, size_bytes, deployment_package_uri)
        """

        CONFIG_FILES = {
            "python": ["handler.py", "requirements.txt", ".python_packages"],
            "nodejs": ["handler.js", "package.json", "node_modules"],
        }
        package_config = CONFIG_FILES[language_name]
        function_dir = os.path.join(directory, "function")
        os.makedirs(function_dir)
        # move all files to 'function' except handler.py
        for file in os.listdir(directory):
            if file not in package_config:
                file = os.path.join(directory, file)
                shutil.move(file, function_dir)

        bytes_size = os.path.getsize(directory)
        mbytes = bytes_size / 1024.0 / 1024.0
        self.logging.info("Function size {:2f} MB".format(mbytes))

        return directory, bytes_size, ""

    def _start_container(
        self, code_package: Benchmark, func_name: str, func: Optional[LocalFunction]
    ) -> LocalFunction:
        """Start a Docker container for function execution.

        Creates and starts a Docker container running the function code. Handles
        port allocation, environment setup, volume mounting, and health checking.
        Optionally starts memory measurement processes.

        Args:
            code_package: Benchmark code package to deploy
            func_name: Name of the function
            func: Optional existing function to update (for restarts)

        Returns:
            LocalFunction: Running function instance

        Raises:
            RuntimeError: If port allocation fails or container won't start
        """

        container_name = "{}:run.local.{}.{}".format(
            self._system_config.docker_repository(),
            code_package.language_name,
            code_package.language_version,
        )

        environment = {
            "CONTAINER_UID": str(os.getuid()),
            "CONTAINER_GID": str(os.getgid()),
            "CONTAINER_USER": self._system_config.username(self.name(), code_package.language_name),
        }
        if self.config.resources.storage_config:

            environment = {**self.config.resources.storage_config.envs(), **environment}

        if code_package.uses_nosql:

            nosql_storage = self.system_resources.get_nosql_storage()
            environment = {**environment, **nosql_storage.envs()}

            for original_name, actual_name in nosql_storage.get_tables(
                code_package.benchmark
            ).items():
                environment[f"NOSQL_STORAGE_TABLE_{original_name}"] = actual_name

        # FIXME: make CPUs configurable
        # FIXME: configure memory
        # FIXME: configure timeout
        # cpuset_cpus=cpuset,
        # required to access perf counters
        # alternative: use custom seccomp profile
        container_kwargs = {
            "image": container_name,
            "command": f"/bin/bash /sebs/run_server.sh {self.DEFAULT_PORT}",
            "volumes": {code_package.code_location: {"bind": "/function", "mode": "ro"}},
            "environment": environment,
            "privileged": True,
            "security_opt": ["seccomp:unconfined"],
            "network_mode": "bridge",
            "remove": self.remove_containers,
            "stdout": True,
            "stderr": True,
            "detach": True,
            # "tty": True,
        }

        # If SeBS is running on non-linux platforms,
        # container port must be mapped to host port to make it reachable
        # Check if the system is NOT Linux or that it is WSL
        port = self.DEFAULT_PORT
        if not is_linux():
            port_found = False
            for p in range(self.DEFAULT_PORT, self.DEFAULT_PORT + 1000):
                # check no container has been deployed on docker's port p
                if p not in self.config.resources.allocated_ports:
                    # check if port p on the host is free
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                        try:
                            s.bind(("127.0.0.1", p))
                            # The port is available
                            port = p
                            port_found = True
                            self.config.resources.allocated_ports.add(p)
                            break
                        except socket.error:
                            # The port is already in use
                            continue

            if not port_found:
                raise RuntimeError(
                    f"Failed to allocate port for container: No ports available between "
                    f"{self.DEFAULT_PORT} and {self.DEFAULT_PORT + 999}"
                )

            container_kwargs["command"] = f"/bin/bash /sebs/run_server.sh {port}"
            container_kwargs["ports"] = {f"{port}/tcp": port}

        container = self._docker_client.containers.run(**container_kwargs)

        pid: Optional[int] = None
        if self.measurements_enabled and self._memory_measurement_path is not None:
            # launch subprocess to measure memory
            proc = subprocess.Popen(
                [
                    "python3",
                    "./sebs/local/measureMem.py",
                    "--container-id",
                    container.id,
                    "--measure-interval",
                    str(self._measure_interval),
                    "--measurement-file",
                    self._memory_measurement_path,
                ]
            )
            pid = proc.pid

        if func is None:
            function_cfg = FunctionConfig.from_benchmark(code_package)
            func = LocalFunction(
                container,
                port,
                func_name,
                code_package.benchmark,
                code_package.hash,
                function_cfg,
                pid,
            )
        else:
            func.container = container
            func._measurement_pid = pid

        # Wait until server starts
        max_attempts = 10
        attempts = 0
        while attempts < max_attempts:
            try:
                requests.get(f"http://{func.url}/alive")
                break
            except requests.exceptions.ConnectionError:
                time.sleep(0.25)
                attempts += 1

        if attempts == max_attempts:
            raise RuntimeError(
                f"Couldn't start {func_name} function at container "
                f"{container.id} , running on {func.url}"
            )

        self.logging.info(
            f"Started {func_name} function at container {container.id} , running on {func._url}"
        )

        return func

    def create_function(
        self,
        code_package: Benchmark,
        func_name: str,
        container_deployment: bool,
        container_uri: str,
    ) -> "LocalFunction":
        """Create a new function deployment. In practice, it starts a new Docker container.

        Args:
            code_package: Benchmark code package to deploy
            func_name: Name for the function
            container_deployment: Whether to use container deployment (unsupported)
            container_uri: Container URI (unused for local)

        Returns:
            LocalFunction: Created function instance

        Raises:
            NotImplementedError: If container deployment is requested
        """
        if container_deployment:
            raise NotImplementedError("Container deployment is not supported in Local")
        return self._start_container(code_package, func_name, None)

    def update_function(
        self,
        function: Function,
        code_package: Benchmark,
        container_deployment: bool,
        container_uri: str,
    ) -> None:
        """Update an existing function with new code.

        Stops the existing container and starts a new one with updated code.

        Args:
            function: Existing function to update
            code_package: New benchmark code package
            container_deployment: Whether to use container deployment (unused)
            container_uri: Container URI (unused)
        """
        func = cast(LocalFunction, function)
        func.stop()
        self.logging.info("Allocating a new function container with updated code")
        self._start_container(code_package, function.name, func)

    def create_trigger(self, func: Function, trigger_type: Trigger.TriggerType) -> Trigger:
        """Create a trigger for function invocation.

        For local functions, only HTTP triggers are supported.

        Args:
            func: Function to create trigger for
            trigger_type: Type of trigger to create

        Returns:
            Trigger: Created trigger instance

        Raises:
            RuntimeError: If trigger type is not HTTP
        """
        from sebs.local.function import HTTPTrigger

        function = cast(LocalFunction, func)
        if trigger_type == Trigger.TriggerType.HTTP:
            trigger = HTTPTrigger(function._url)
            trigger.logging_handlers = self.logging_handlers
        else:
            raise RuntimeError("Not supported!")

        function.add_trigger(trigger)
        self.cache_client.update_function(function)
        return trigger

    def cached_function(self, function: Function) -> None:
        """Handle cached function setup.

        For local functions, no special handling is needed for cached functions.

        Args:
            function: Cached function instance
        """
        pass

    def update_function_configuration(self, function: Function, code_package: Benchmark) -> None:
        """Update function configuration.

        Args:
            function: Function to update
            code_package: Benchmark code package

        Raises:
            RuntimeError: Always raised as configuration updates are not supported
        """
        self.logging.error("Updating function configuration of local deployment is not supported")
        raise RuntimeError("Updating function configuration of local deployment is not supported")

    def download_metrics(
        self,
        function_name: str,
        start_time: int,
        end_time: int,
        requests: Dict[str, ExecutionResult],
        metrics: dict,
    ) -> None:
        """Download execution metrics.

        For local execution, metrics are not available from the platform.

        Args:
            function_name: Name of the function
            start_time: Start time for metrics collection
            end_time: End time for metrics collection
            requests: Execution requests to collect metrics for
            metrics: Dictionary to store collected metrics
        """
        pass

    def enforce_cold_start(self, functions: List[Function], code_package: Benchmark) -> None:
        """Enforce cold start for functions.

        Args:
            functions: List of functions to enforce cold start on
            code_package: Benchmark code package

        Raises:
            NotImplementedError: Cold start enforcement is not implemented for local
        """
        raise NotImplementedError()

    @staticmethod
    def default_function_name(
        code_package: Benchmark, resources: Optional[Resources] = None
    ) -> str:
        """Generate default function name.

        Creates a standardized function name based on the code package and resources.

        Args:
            code_package: Benchmark code package
            resources: Optional resources instance for ID inclusion

        Returns:
            str: Generated function name
        """
        # Create function name
        if resources is not None:
            func_name = "sebs-{}-{}-{}-{}".format(
                resources.resources_id,
                code_package.benchmark,
                code_package.language_name,
                code_package.language_version,
            )
        else:
            func_name = "sebd-{}-{}-{}".format(
                code_package.benchmark,
                code_package.language_name,
                code_package.language_version,
            )
        return func_name

    @staticmethod
    def format_function_name(func_name: str) -> str:
        """Format function name for platform requirements.

        For local execution, no formatting is needed.

        Args:
            func_name: Function name to format

        Returns:
            str: Formatted function name (unchanged for local)
        """
        return func_name

    def start_measurements(self, measure_interval: int) -> Optional[str]:
        """Start memory measurements for function containers.

        Creates a temporary file for storing memory measurements and enables
        measurement collection at the specified interval.

        Args:
            measure_interval: Measurement interval in milliseconds

        Returns:
            Optional[str]: Path to measurement file, or None if measurements disabled
        """
        self._measure_interval = measure_interval

        if not self.measurements_enabled:
            return None

        # initialize an empty file for measurements to be written to
        import tempfile
        from pathlib import Path

        fd, self._memory_measurement_path = tempfile.mkstemp()
        Path(self._memory_measurement_path).touch()
        os.close(fd)

        return self._memory_measurement_path
