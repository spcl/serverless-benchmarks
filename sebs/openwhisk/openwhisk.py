"""
Apache OpenWhisk serverless platform implementation for SeBS.

This module provides the main OpenWhisk system class that integrates OpenWhisk
serverless platform with the SeBS benchmarking framework. It handles function
deployment, execution, monitoring, and resource management for OpenWhisk clusters.
"""

import json
import os
import subprocess
from typing import cast, Callable, Dict, List, Optional, Tuple, Type

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
from sebs.utils import LoggingHandlers
from sebs.faas.config import Resources
from .config import OpenWhiskConfig
from .function import OpenWhiskFunction, OpenWhiskFunctionConfig
from ..config import SeBSConfig
from sebs.types import Language


class OpenWhisk(System):
    """
    Apache OpenWhisk serverless platform implementation for SeBS.

    This class provides the main integration between SeBS and Apache OpenWhisk,
    handling function deployment, execution, container management, and resource
    management (primarily self-hosted storage like Minio/ScyllaDB via SelfHostedSystemResources),
    and interaction with the `wsk` CLI.
    It supports OpenWhisk deployments with Docker-based function packaging.
    We do not use code packages due to low package size limits.

    Attributes:
        _config: OpenWhisk-specific configuration settings
        container_client: Docker container client for function packaging
        logging_handlers: Logging handlers for the OpenWhisk system

    Example:
        >>> openwhisk = OpenWhisk(sys_config, ow_config, cache, docker_client, handlers)
        >>> function = openwhisk.create_function(benchmark, "test-func", True, "image:tag")
    """

    _config: OpenWhiskConfig

    def __init__(
        self,
        system_config: SeBSConfig,
        config: OpenWhiskConfig,
        cache_client: Cache,
        docker_client: docker.client.DockerClient,
        logger_handlers: LoggingHandlers,
    ) -> None:
        """
        Initialize OpenWhisk system with configuration and clients.
        Will log in to Docker registry.

        Args:
            system_config: Global SeBS system configuration
            config: OpenWhisk-specific configuration settings
            cache_client: Cache client for storing function and resource data
            docker_client: Docker client for container operations
            logger_handlers: Logging handlers for system operations
        """
        super().__init__(
            system_config,
            cache_client,
            docker_client,
            SelfHostedSystemResources(
                "openwhisk", config, cache_client, docker_client, logger_handlers
            ),
        )
        self._config = config
        self.logging_handlers = logger_handlers

        self._container_client = OpenWhiskContainer(
            self.system_config,
            self.config,
            self.docker_client,
            self.config.experimentalManifest,
        )

        if self.config.resources.docker_username:
            if self.config.resources.docker_registry:
                docker_client.login(
                    username=self.config.resources.docker_username,
                    password=self.config.resources.docker_password,
                    registry=self.config.resources.docker_registry,
                )
            else:
                docker_client.login(
                    username=self.config.resources.docker_username,
                    password=self.config.resources.docker_password,
                )

    def initialize(
        self, config: Dict[str, str] = {}, resource_prefix: Optional[str] = None
    ) -> None:
        """
        Initialize OpenWhisk system resources.

        Args:
            config: Additional configuration parameters (currently unused)
            resource_prefix: Optional prefix for resource naming
        """
        self.initialize_resources(select_prefix=resource_prefix)

    @property
    def config(self) -> OpenWhiskConfig:
        """
        Get OpenWhisk configuration.

        Returns:
            OpenWhisk configuration instance
        """
        return self._config

    @property
    def container_client(self) -> OpenWhiskContainer:
        """
        Get OpenWhisk container client.

        Returns:
            OpenWhisk container client
        """
        return self._container_client

    def shutdown(self) -> None:
        """
        Shutdown OpenWhisk system and clean up resources.

        This method stops storage services if configured and optionally
        removes the OpenWhisk cluster based on configuration settings.
        """
        if hasattr(self, "storage") and self.config.shutdownStorage:
            self.storage.stop()
        if self.config.removeCluster:
            from tools.openwhisk_preparation import delete_cluster  # type: ignore

            delete_cluster()
        super().shutdown()

    @staticmethod
    def name() -> str:
        """
        Get the platform name identifier.

        Returns:
            Platform name as string
        """
        return "openwhisk"

    @staticmethod
    def typename() -> str:
        """
        Get the platform type name.

        Returns:
            Platform type name as string
        """
        return "OpenWhisk"

    @staticmethod
    def function_type() -> "Type[Function]":
        """
        Get the function type for this platform.

        Returns:
            OpenWhiskFunction class type
        """
        return OpenWhiskFunction

    def get_wsk_cmd(self) -> List[str]:
        """
        Get the WSK CLI command with appropriate flags.

        Returns:
            List of command arguments for WSK CLI execution
        """
        cmd = [self.config.wsk_exec]
        if self.config.wsk_bypass_security:
            cmd.append("-i")
        return cmd

    def package_code(
        self,
        directory: str,
        language: Language,
        language_version: str,
        architecture: str,
        benchmark: str,
        is_cached: bool,
    ) -> Tuple[str, int]:

        """
        Package benchmark code for OpenWhisk deployment.

        Creates a a ZIP archive containing the benchmark code.
        The ZIP archive is required for OpenWhisk function registration even when
        using Docker-based deployment. It contains only the main handlers
        (`__main__.py` or `index.js`). The Docker image URI is returned,
        which will be used when creating the action.

        Args:
            directory: Path to the benchmark code directory
            language: Programming language (e.g., 'python', 'nodejs')
            language_version: Language version (e.g., '3.8', '14')
            architecture: Target architecture (e.g., 'x86_64')
            benchmark: Benchmark name
            is_cached: Whether Docker image is already cached

        Returns:
            Tuple containing:
                - Path to created ZIP archive
                - Size of ZIP archive in bytes
        """

        if language != Language.JAVA:
            # We deploy Minio config in code package since this depends on local
            # deployment - it cannnot be a part of Docker image
            # FIXME: why No file is needed for Java?
            CONFIG_FILES = {
                "python": ["__main__.py"],
                "nodejs": ["index.js"],
            }
            package_config = CONFIG_FILES[language]
        else:
            package_config = []

        benchmark_archive = os.path.join(directory, f"{benchmark}.zip")
        subprocess.run(
            ["zip", benchmark_archive] + package_config,
            stdout=subprocess.DEVNULL,
            cwd=directory,
        )
        self.logging.info(f"Created {benchmark_archive} archive")
        bytes_size = os.path.getsize(benchmark_archive)
        self.logging.info("Zip archive size {:2f} MB".format(bytes_size / 1024.0 / 1024.0))
        return benchmark_archive, bytes_size

    def finalize_container_build(
        self,
    ) -> Callable[[str, Language, str, str, str, bool], Tuple[str, int]] | None:
        """
        Regardless of Docker image status, we need to create .zip file
        to allow registration of function with OpenWhisk.
        By returning the code package routine, we ensure that a package
        will be created.

        Returns:
            Code packaging function.
        """
        return self.package_code

    def storage_arguments(self, code_package: Benchmark) -> List[str]:
        """
        Generate storage-related arguments for function deployment.

        Creates WSK CLI parameters for Minio object storage and ScyllaDB NoSQL
        storage configurations based on the benchmark requirements.

        Args:
            code_package: Benchmark configuration requiring storage access

        Returns:
            List of WSK CLI parameter arguments for storage configuration
        """
        envs = []

        if self.config.resources.storage_config:
            storage_envs = self.config.resources.storage_config.envs()
            envs = [
                "-p",
                "MINIO_STORAGE_SECRET_KEY",
                storage_envs["MINIO_SECRET_KEY"],
                "-p",
                "MINIO_STORAGE_ACCESS_KEY",
                storage_envs["MINIO_ACCESS_KEY"],
                "-p",
                "MINIO_STORAGE_CONNECTION_URL",
                storage_envs["MINIO_ADDRESS"],
            ]

        if code_package.uses_nosql:
            nosql_storage = self.system_resources.get_nosql_storage()
            for key, value in nosql_storage.envs().items():
                envs.append("-p")
                envs.append(key)
                envs.append(value)

            for original_name, actual_name in nosql_storage.get_tables(
                code_package.benchmark
            ).items():
                envs.append("-p")
                envs.append(f"NOSQL_STORAGE_TABLE_{original_name}")
                envs.append(actual_name)

        return envs

    def create_function(
        self,
        code_package: Benchmark,
        func_name: str,
        container_deployment: bool,
        container_uri: str | None,
    ) -> "OpenWhiskFunction":
        """
        Create or retrieve an OpenWhisk function (action).

        This method checks if a function already exists and updates it if necessary,
        or creates a new function with the appropriate configuration, storage settings,
        and Docker image.

        Args:
            code_package: Benchmark configuration and code package
            func_name: Name for the OpenWhisk action
            container_deployment: Whether to use container-based deployment
            container_uri: URI of the Docker image for the function

        Returns:
            OpenWhiskFunction instance configured with LibraryTrigger

        Raises:
            RuntimeError: If WSK CLI is not accessible or function creation fails
        """

        if not container_deployment:
            raise RuntimeError("Non-container deployment is not supported in OpenWhisk!")

        self.logging.info("Creating function as an action in OpenWhisk.")
        try:
            actions = subprocess.run(
                [*self.get_wsk_cmd(), "action", "list"],
                stderr=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
            )

            function_found = False
            docker_image = ""
            for line in actions.stdout.decode().split("\n"):
                if line and func_name in line.split()[0]:
                    function_found = True
                    break

            function_cfg = OpenWhiskFunctionConfig.from_benchmark(code_package)
            if code_package.uses_storage:
                function_cfg.object_storage = cast(
                    Minio, self.system_resources.get_storage()
                ).config
            if code_package.uses_nosql:
                function_cfg.nosql_storage = cast(
                    ScyllaDB, self.system_resources.get_nosql_storage()
                ).config
            if function_found:
                # docker image is overwritten by the update
                res = OpenWhiskFunction(
                    func_name, code_package.benchmark, code_package.hash, function_cfg
                )
                # Update function - we don't know what version is stored
                self.logging.info(f"Retrieved existing OpenWhisk action {func_name}.")
                self.update_function(res, code_package, container_deployment, container_uri)
            else:
                try:
                    self.logging.info(f"Creating new OpenWhisk action {func_name}")
                    docker_image = self.system_config.benchmark_image_name(
                        self.name(),
                        code_package.benchmark,
                        code_package.language_name,
                        code_package.language_version,
                        code_package.architecture,
                        repository=self.config.dockerhub_repository,
                    )

                    run_arguments = [
                        *self.get_wsk_cmd(),
                        "action",
                        "create",
                        func_name,
                        "--web",
                        "true",
                        "--docker",
                        docker_image,
                        "--memory",
                        str(code_package.benchmark_config.memory),
                        "--timeout",
                        str(code_package.benchmark_config.timeout * 1000),
                        *self.storage_arguments(code_package),
                        code_package.code_location,
                    ]
                    if code_package.language == Language.JAVA:
                        run_arguments.extend(["--main", "Main"])

                    if code_package.code_location is None:
                        raise RuntimeError(
                            "Code location must be set for OpenWhisk action! "
                            "OpenWhisk requires container deployment with a code package."
                        )

                    subprocess.run(
                        run_arguments,
                        stderr=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        check=True,
                    )

                    function_cfg.docker_image = docker_image
                    res = OpenWhiskFunction(
                        func_name,
                        code_package.benchmark,
                        code_package.hash,
                        function_cfg,
                    )
                except subprocess.CalledProcessError as e:
                    self.logging.error(f"Cannot create action {func_name}.")
                    self.logging.error(f"Output: {e.stderr.decode('utf-8')}")
                    raise RuntimeError(e)

        except FileNotFoundError:
            self.logging.error("Could not retrieve OpenWhisk functions - is path to wsk correct?")
            raise RuntimeError("Failed to access wsk binary")

        # Add LibraryTrigger to a new function
        trigger = LibraryTrigger(func_name, self.get_wsk_cmd())
        trigger.logging_handlers = self.logging_handlers
        res.add_trigger(trigger)

        return res

    def update_function(
        self,
        function: Function,
        code_package: Benchmark,
        container_deployment: bool,
        container_uri: str | None,
    ) -> None:
        """
        Update an existing OpenWhisk function with new code and configuration.

        Args:
            function: Existing function to update
            code_package: New benchmark configuration and code package
            container_deployment: Whether to use container-based deployment
            container_uri: URI of the new Docker image

        Raises:
            RuntimeError: If WSK CLI is not accessible or update fails
        """
        if not container_deployment:
            raise RuntimeError(
                "Code location must be set for OpenWhisk action! "
                "OpenWhisk requires container deployment with a code package."
            )

        self.logging.info(f"Update an existing OpenWhisk action {function.name}.")
        function = cast(OpenWhiskFunction, function)
        docker_image = self.system_config.benchmark_image_name(
            self.name(),
            code_package.benchmark,
            code_package.language_name,
            code_package.language_version,
            code_package.architecture,
            repository=self.config.dockerhub_repository,
        )

        if code_package.code_location is None:
            raise RuntimeError(
                "Code location must be set for OpenWhisk action! "
                "OpenWhisk requires container deployment with a code package."
            )

        try:
            subprocess.run(
                [
                    *self.get_wsk_cmd(),
                    "action",
                    "update",
                    function.name,
                    "--web",
                    "true",
                    "--docker",
                    docker_image,
                    "--memory",
                    str(code_package.benchmark_config.memory),
                    "--timeout",
                    str(code_package.benchmark_config.timeout * 1000),
                    *self.storage_arguments(code_package),
                    code_package.code_location,
                ],
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
                check=True,
            )
            function.config.docker_image = docker_image

        except FileNotFoundError as e:
            self.logging.error("Could not update OpenWhisk function - is path to wsk correct?")
            raise RuntimeError(e)
        except subprocess.CalledProcessError as e:
            self.logging.error(f"Unknown error when running function update: {e}!")
            self.logging.error("Make sure to remove SeBS cache after restarting OpenWhisk!")
            self.logging.error(f"Output: {e.stderr.decode('utf-8')}")
            raise RuntimeError(e)

    def update_function_configuration(self, function: Function, code_package: Benchmark) -> None:
        """
        Update configuration of an existing OpenWhisk function.

        Updates memory allocation, timeout, and storage parameters without
        changing the function code or Docker image.

        Args:
            function: Function to update configuration for
            code_package: New benchmark configuration settings

        Raises:
            RuntimeError: If WSK CLI is not accessible or configuration update fails
        """
        self.logging.info(f"Update configuration of an existing OpenWhisk action {function.name}.")
        try:
            subprocess.run(
                [
                    *self.get_wsk_cmd(),
                    "action",
                    "update",
                    function.name,
                    "--memory",
                    str(code_package.benchmark_config.memory),
                    "--timeout",
                    str(code_package.benchmark_config.timeout * 1000),
                    *self.storage_arguments(code_package),
                ],
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
                check=True,
            )
        except FileNotFoundError as e:
            self.logging.error("Could not update OpenWhisk function - is path to wsk correct?")
            raise RuntimeError(e)
        except subprocess.CalledProcessError as e:
            self.logging.error(f"Unknown error when running function update: {e}!")
            self.logging.error("Make sure to remove SeBS cache after restarting OpenWhisk!")
            self.logging.error(f"Output: {e.stderr.decode('utf-8')}")
            raise RuntimeError(e)

    def is_configuration_changed(self, cached_function: Function, benchmark: Benchmark) -> bool:
        """
        Check if function configuration has changed compared to cached version.

        Compares current benchmark configuration and storage settings with the
        cached function configuration to determine if an update is needed.

        Args:
            cached_function: Previously cached function configuration
            benchmark: Current benchmark configuration to compare against

        Returns:
            True if configuration has changed and function needs updating
        """
        changed = super().is_configuration_changed(cached_function, benchmark)

        if benchmark.uses_storage:
            storage = cast(Minio, self.system_resources.get_storage())
            function = cast(OpenWhiskFunction, cached_function)
            # check if now we're using a new storage
            if function.config.object_storage != storage.config:
                self.logging.info(
                    "Updating function configuration due to changed storage configuration."
                )
                changed = True
                function.config.object_storage = storage.config

        if benchmark.uses_nosql:
            nosql_storage = cast(ScyllaDB, self.system_resources.get_nosql_storage())
            function = cast(OpenWhiskFunction, cached_function)
            # check if now we're using a new storage
            if function.config.nosql_storage != nosql_storage.config:
                self.logging.info(
                    "Updating function configuration due to changed NoSQL storage configuration."
                )
                changed = True
                function.config.nosql_storage = nosql_storage.config

        return changed

    def default_function_name(
        self, code_package: Benchmark, resources: Optional[Resources] = None
    ) -> str:
        """
        Generate default function name based on benchmark and resource configuration.

        Args:
            code_package: Benchmark package containing name and language info
            resources: Optional specific resources to use for naming

        Returns:
            Generated function name string
        """
        resource_id = resources.resources_id if resources else self.config.resources.resources_id
        return (
            f"sebs-{resource_id}-{code_package.benchmark}-"
            f"{code_package.language_name}-{code_package.language_version}"
        )

    def enforce_cold_start(self, functions: List[Function], code_package: Benchmark) -> None:
        """
        Enforce cold start for functions (not implemented for OpenWhisk).

        Args:
            functions: List of functions to enforce cold start for
            code_package: Benchmark package configuration

        Raises:
            NotImplementedError: Cold start enforcement not implemented for OpenWhisk
        """
        raise NotImplementedError()

    def download_metrics(
        self,
        function_name: str,
        start_time: int,
        end_time: int,
        requests: Dict[str, ExecutionResult],
        metrics: dict,
    ):
        """
        Download metrics for function executions (no-op for OpenWhisk).

        Args:
            function_name: Name of the function to download metrics for
            start_time: Start time for metrics collection (epoch timestamp)
            end_time: End time for metrics collection (epoch timestamp)
            requests: Dictionary mapping request IDs to execution results
            metrics: Dictionary to store downloaded metrics

        Note:
            OpenWhisk metrics collection is not currently implemented.
        """

        self.logging.info(
            f"OpenWhisk: Starting to download metrics for {len(requests)} invocations"
        )

        processed_count = 0

        for request_id in requests:
            try:
                result = subprocess.run(
                    [*self.get_wsk_cmd(), "activation", "get", request_id],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )

                if result.returncode != 0:
                    self.logging.warning(f"OpenWhisk: Activation {request_id} not found")
                    continue

                # Parse JSON output (skip first "ok" line)
                output = result.stdout.decode("utf-8")
                lines = output.strip().split("\n")
                if len(lines) <= 1:
                    self.logging.warning(f"OpenWhisk: Activation {request_id} not found")
                    continue

                json_str = "\n".join(lines[1:])
                activation = json.loads(json_str)

                duration_ms = activation.get("duration")
                if duration_ms is None:
                    self.logging.error(f"OpenWhisk: Duration not found in activation {request_id}")
                    continue

                # Update execution time (convert milliseconds to microseconds)
                requests[request_id].provider_times.execution = int(float(duration_ms) * 1000)

                # Extract initTime from annotations (optional - only present on cold starts)
                annotations = activation.get("annotations", [])
                for annotation in annotations:
                    if annotation.get("key") == "initTime":
                        init_time_ms = annotation.get("value")
                        if init_time_ms is not None:
                            requests[request_id].provider_times.initialization = int(
                                float(init_time_ms) * 1000
                            )
                        break

                processed_count += 1

            except json.JSONDecodeError as e:
                self.logging.error(
                    f"OpenWhisk: Failed to parse activation JSON for {request_id}: {e}"
                )
            except Exception as e:
                self.logging.error(f"OpenWhisk: Error processing activation {request_id}: {e}")

        self.logging.info(
            f"OpenWhisk: Downloaded metrics for {processed_count} "
            f"out of {len(requests)} invocations"
        )

    def create_trigger(self, function: Function, trigger_type: Trigger.TriggerType) -> Trigger:
        """
        Create a trigger for function invocation.

        Args:
            function: Function to create trigger for
            trigger_type: Type of trigger to create (LIBRARY or HTTP)

        Returns:
            Created trigger instance

        Raises:
            RuntimeError: If WSK CLI is not accessible or trigger type not supported
        """
        if trigger_type == Trigger.TriggerType.LIBRARY:
            return function.triggers(Trigger.TriggerType.LIBRARY)[0]
        elif trigger_type == Trigger.TriggerType.HTTP:
            try:
                response = subprocess.run(
                    [*self.get_wsk_cmd(), "action", "get", function.name, "--url"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    check=True,
                )
            except FileNotFoundError as e:
                self.logging.error(
                    "Could not retrieve OpenWhisk configuration - is path to wsk correct?"
                )
                raise RuntimeError(e)
            stdout = response.stdout.decode("utf-8")
            url = stdout.strip().split("\n")[-1] + ".json"
            trigger = HTTPTrigger(function.name, url)
            trigger.logging_handlers = self.logging_handlers
            function.add_trigger(trigger)
            self.cache_client.update_function(function)
            return trigger
        else:
            raise RuntimeError("Not supported!")

    def cached_function(self, function: Function) -> None:
        """
        Configure a cached function with current system settings.

        Updates triggers with current logging handlers and WSK command configuration.

        Args:
            function: Cached function to configure
        """
        for trigger in function.triggers(Trigger.TriggerType.LIBRARY):
            trigger.logging_handlers = self.logging_handlers
            cast(LibraryTrigger, trigger).wsk_cmd = self.get_wsk_cmd()
        for trigger in function.triggers(Trigger.TriggerType.HTTP):
            trigger.logging_handlers = self.logging_handlers

    def disable_rich_output(self) -> None:
        """
        Disable rich output formatting for container operations.

        This is useful for non-interactive environments or when plain text
        output is preferred.
        """
        self.container_client.disable_rich_output = True
