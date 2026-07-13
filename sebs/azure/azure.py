# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
"""Azure serverless platform implementation for SeBS benchmarking.

This module provides the Azure implementation of the SeBS serverless
benchmarking system. It handles Azure Functions deployment, resource
management, code packaging, and benchmark execution on Microsoft Azure.

Key features:
    - Azure Functions deployment and management
    - Azure Storage integration for code and data
    - CosmosDB support for NoSQL benchmarks
    - HTTP trigger configuration and invocation
    - Performance metrics collection via Application Insights
    - Resource lifecycle management

The main class Azure extends the base System class to provide Azure-specific
functionality for serverless function benchmarking.

Example:
    Basic usage for Azure benchmarking::

        from sebs.azure.azure import Azure
        from sebs.azure.config import AzureConfig

        # Initialize Azure system with configuration
        azure_system = Azure(sebs_config, azure_config, cache, docker_client, handlers)
        azure_system.initialize()

        # Deploy and benchmark functions
        function = azure_system.create_function(code_package, func_name, False, "")
        result = function.invoke(payload)
"""

import datetime
import glob
import hashlib
import json
import random
import re
import os
import shlex
import shutil
import time
import uuid
from typing import cast, Dict, List, Optional, Set, Tuple, Type  # noqa

import docker

from sebs.azure.blob_storage import BlobStorage
from sebs.azure.cli import AzureCLI
from sebs.azure.cosmosdb import CosmosDB
from sebs.azure.function import AzureFunction, AzureWorkflow
from sebs.azure.config import AzureConfig, AzureResources
from sebs.azure.system_resources import AzureSystemResources
from sebs.azure.triggers import AzureTrigger, HTTPTrigger
from sebs.faas.function import Trigger
from sebs.benchmark import Benchmark
from sebs.cache import Cache
from sebs.config import SeBSConfig
from sebs.experiments.config import SystemVariant
from sebs.utils import LoggingHandlers, execute
from sebs.faas.function import Function, FunctionConfig, ExecutionResult, Workflow
from sebs.faas.system import System
from sebs.faas.config import Resources
from sebs.sebs_types import Language


class Azure(System):
    """Azure serverless platform implementation.

    This class implements the Azure-specific functionality for the SeBS
    benchmarking suite. It handles Azure Functions deployment, resource
    management, and benchmark execution on Microsoft Azure platform.

    Attributes:
        logs_client: Azure logs client (currently unused)
        storage: BlobStorage instance for Azure Blob Storage operations
        cached: Flag indicating if resources are cached
        _config: Azure configuration containing credentials and resources
        AZURE_RUNTIMES: Mapping of language names to Azure runtime identifiers
    """

    logs_client = None
    storage: BlobStorage
    cached: bool = False
    _config: AzureConfig

    # runtime mapping
    AZURE_RUNTIMES = {"python": "python", "nodejs": "node", "java": "java"}

    @staticmethod
    def name() -> str:
        """Get the platform name.

        Returns:
            Platform name 'azure'.
        """
        return "azure"

    @staticmethod
    def _normalize_runtime_version(language: str, version: str) -> str:
        """
        Azure Functions Java expects versions with a minor component
        (e.g. 17.0 instead of 17). Other languages can keep the version
        as-is.
        """
        if language == "java" and re.match(r"^\d+$", str(version)):
            return f"{version}.0"
        return version

    @property
    def config(self) -> AzureConfig:
        """Get Azure configuration.

        Returns:
            Azure configuration containing credentials and resources.
        """
        return self._config

    @staticmethod
    def function_type() -> Type[Function]:
        """Get the function type for Azure.

        Returns:
            AzureFunction class type.
        """
        return AzureFunction

    @staticmethod
    def workflow_type() -> Type[Workflow]:
        """Get the workflow type for Azure.

        Returns:
            AzureWorkflow class type.
        """
        return AzureWorkflow

    @property
    def cli_instance(self) -> AzureCLI:
        """Get Azure CLI instance.

        Returns:
            Azure CLI instance for executing Azure commands.
        """
        return cast(AzureSystemResources, self._system_resources).cli_instance

    def __init__(
        self,
        sebs_config: SeBSConfig,
        config: AzureConfig,
        cache_client: Cache,
        docker_client: docker.client.DockerClient,
        logger_handlers: LoggingHandlers,
    ) -> None:
        """Initialize Azure system.

        Args:
            sebs_config: SeBS configuration settings
            config: Azure-specific configuration
            cache_client: Cache for storing function and resource data
            docker_client: Docker client for container operations
            logger_handlers: Logging handlers for output management
        """
        super().__init__(
            sebs_config,
            cache_client,
            docker_client,
            AzureSystemResources(sebs_config, config, cache_client, docker_client, logger_handlers),
        )
        self.logging_handlers = logger_handlers
        self._config = config

    def initialize(
        self,
        config: Dict[str, str] = {},
        resource_prefix: Optional[str] = None,
        quiet: bool = False,
    ) -> None:
        """Initialize Azure system and start CLI container.

        Initializes Azure resources and allocates shared resources like
        data storage account. Starts the Docker container with Azure CLI tools.

        Args:
            config: Additional configuration parameters
            resource_prefix: Optional prefix for resource naming
        """
        self.initialize_resources(select_prefix=resource_prefix, quiet=quiet)
        self.allocate_shared_resource()

    def shutdown(self) -> None:
        """Shutdown Azure system and cleanup resources.

        Stops the Azure CLI container and performs cleanup of system resources.
        """
        cast(AzureSystemResources, self._system_resources).shutdown()
        super().shutdown()

    def find_deployments(self) -> List[str]:
        """Find existing SeBS deployments by scanning resource groups.

        Looks for Azure resource groups matching the SeBS naming pattern
        - sebs_resource_group_(.*) - to identify existing deployments
        that can be reused.

        Returns:
            List of deployment identifiers found in resource groups.
        """
        resource_groups = self.config.resources.list_resource_groups(self.cli_instance)
        deployments = []
        for group in resource_groups:
            # The benchmarks bucket must exist in every deployment.
            deployment_search = re.match("sebs_resource_group_(.*)", group)
            if deployment_search:
                deployments.append(deployment_search.group(1))

        return deployments

    def allocate_shared_resource(self) -> None:
        """Allocate shared data storage account.

        Creates or retrieves the shared data storage account used for
        benchmark input/output data. This allows multiple deployment
        clients to share the same storage, simplifying regression testing.
        """
        self.config.resources.data_storage_account(self.cli_instance)

    def package_code(
        self,
        directory: str,
        language: Language,
        language_version: str,
        architecture: str,
        benchmark: str,
        is_cached: bool,
    ) -> Tuple[str, float]:
        """Package function code for Azure Functions deployment.

        Creates the proper directory structure and configuration files
        required for Azure Functions deployment. For regular functions:
        - handler/ directory with source files and Azure wrappers
        - function.json with trigger and binding configuration

        For workflows (Durable Functions):
        - main/ directory with HTTP trigger + durableClient binding
        - run_workflow/ directory with orchestration trigger
        - run_subworkflow/ directory with orchestration trigger
        - One directory per activity function with activityTrigger binding

        Both include host.json with runtime configuration.

        Args:
            directory: Directory containing the function code
            language: Programming language (python, nodejs)
            language_version: Language runtime version
            architecture: Target architecture (currently unused)
            benchmark: Name of the benchmark
            is_cached: Whether the package is from cache

        Returns:
            Tuple of (directory_path, code_size_bytes)
        """
        is_workflow = os.path.exists(os.path.join(directory, "definition.json"))

        if is_workflow:
            return self._package_code_workflow(directory, language, benchmark)
        else:
            return self._package_code_function(directory, language, benchmark)

    def _package_code_function(
        self, directory: str, language: Language, benchmark: str
    ) -> Tuple[str, float]:
        """Package a regular (non-workflow) function for Azure."""

        EXEC_FILES = {
            Language.PYTHON: "handler.py",
            Language.NODEJS: "handler.js",
            Language.JAVA: "../lib/function.jar",
        }
        CONFIG_FILES = {
            Language.PYTHON: ["requirements.txt", ".python_packages"],
            Language.NODEJS: ["package.json", "node_modules"],
            Language.JAVA: ["lib", "src", "pom.xml", "target", ".mvn", "mvnw", "mvnw.cmd"],
        }
        WORKFLOW_FILES = [
            "main_workflow.py",
            "run_workflow.py",
            "run_subworkflow.py",
            "fsm.py",
        ]
        package_config = CONFIG_FILES[language]

        handler_dir = os.path.join(directory, "handler")
        os.makedirs(handler_dir)

        # For Java, create lib directory for JARs and exclude build artifacts
        if language == Language.JAVA:
            lib_dir = os.path.join(directory, "lib")
            os.makedirs(lib_dir, exist_ok=True)
            if os.path.exists(os.path.join(directory, "function.jar")):
                shutil.move(
                    os.path.join(directory, "function.jar"), os.path.join(lib_dir, "function.jar")
                )

        # move all files to 'handler' except package config and workflow files
        for f in os.listdir(directory):
            if f not in package_config and f not in WORKFLOW_FILES:
                source_file = os.path.join(directory, f)
                shutil.move(source_file, handler_dir)

        # Remove workflow files that shouldn't be deployed
        for wf_file in WORKFLOW_FILES:
            wf_path = os.path.join(directory, wf_file)
            if os.path.exists(wf_path):
                os.remove(wf_path)

        # For Java, clean up build artifacts that we don't want to deploy
        if language == Language.JAVA:
            for artifact in ["src", "pom.xml", "target", ".mvn", "mvnw", "mvnw.cmd"]:
                artifact_path = os.path.join(directory, artifact)
                if os.path.exists(artifact_path):
                    if os.path.isdir(artifact_path):
                        shutil.rmtree(artifact_path)
                    else:
                        os.remove(artifact_path)

        # generate function.json
        if language == Language.JAVA:
            default_function_json = {
                "scriptFile": "../lib/function.jar",
                "entryPoint": "org.serverlessbench.Handler.handleRequest",
                "bindings": [
                    {
                        "type": "httpTrigger",
                        "direction": "in",
                        "name": "req",
                        "methods": ["get", "post"],
                        "authLevel": "anonymous",
                    },
                    {"type": "http", "direction": "out", "name": "$return"},
                ],
            }
        else:
            default_function_json = {
                "scriptFile": EXEC_FILES[language],
                "bindings": [
                    {
                        "authLevel": "anonymous",
                        "type": "httpTrigger",
                        "direction": "in",
                        "name": "req",
                        "methods": ["get", "post"],
                    },
                    {"type": "http", "direction": "out", "name": "$return"},
                ],
            }
        json_out = os.path.join(directory, "handler", "function.json")
        json.dump(default_function_json, open(json_out, "w"), indent=2)

        # generate host.json
        default_host_json = {
            "version": "2.0",
            "extensionBundle": {
                "id": "Microsoft.Azure.Functions.ExtensionBundle",
                "version": "[4.0.0, 5.0.0)",
            },
        }
        json.dump(default_host_json, open(os.path.join(directory, "host.json"), "w"), indent=2)

        code_size = Benchmark.directory_size(directory)
        execute("zip -qu -r9 {}.zip * .".format(benchmark), shell=True, cwd=directory)
        return directory, code_size

    def _package_code_workflow(
        self, directory: str, language: Language, benchmark: str
    ) -> Tuple[str, float]:
        """Package a Durable Functions workflow for Azure.

        Creates the directory structure expected by Azure Durable Functions:
        - main/ — HTTP trigger entry point (durableClient binding)
        - run_workflow/ — orchestrator function
        - run_subworkflow/ — sub-orchestrator for parallel map tasks
        - {activity_name}/ — one directory per activity function
        """
        FILES = {"python": "*.py", "nodejs": "*.js"}
        CONFIG_FILES = {
            "python": ["requirements.txt", ".python_packages"],
            "nodejs": ["package.json", "node_modules"],
        }
        WRAPPER_FILES = {
            "python": ["handler.py", "storage.py", "nosql.py", "fsm.py"],
            "nodejs": ["handler.js", "storage.js"],
        }
        file_type = FILES[language]
        package_config = CONFIG_FILES[language]
        wrapper_files = WRAPPER_FILES[language]

        # Rename main_workflow.py to main.py
        main_path = os.path.join(directory, "main_workflow.py")
        os.rename(main_path, os.path.join(directory, "main.py"))

        # Copy definition.json into the package
        # It's loaded at runtime by the orchestrator
        definition_src = None
        for parent in [directory]:
            candidate = os.path.join(parent, "definition.json")
            if os.path.exists(candidate):
                definition_src = candidate
                break
        if definition_src is None:
            raise ValueError(f"No workflow definition found in {directory}")

        # Bindings for different function types
        main_bindings = [
            {
                "name": "req",
                "type": "httpTrigger",
                "direction": "in",
                "authLevel": "anonymous",
                "methods": ["get", "post"],
            },
            {"name": "starter", "type": "durableClient", "direction": "in"},
            {"name": "$return", "type": "http", "direction": "out"},
        ]
        activity_bindings = [
            {"name": "event", "type": "activityTrigger", "direction": "in"},
        ]
        orchestrator_bindings = [
            {"name": "context", "type": "orchestrationTrigger", "direction": "in"}
        ]

        bindings = {
            "main": main_bindings,
            "run_workflow": orchestrator_bindings,
            "run_subworkflow": orchestrator_bindings,
        }

        # Move each .py file into its own directory (Azure Functions convention)
        func_dirs = []
        for file_path in glob.glob(os.path.join(directory, file_type)):
            file = os.path.basename(file_path)

            if file in package_config or file in wrapper_files:
                continue

            name, ext = os.path.splitext(file)
            func_dir = os.path.join(directory, name)
            func_dirs.append(func_dir)

            os.makedirs(func_dir)
            target_file = os.path.join(func_dir, file)
            shutil.move(os.path.join(directory, file), target_file)

            # Generate function.json for each function directory
            script_file = file if name in bindings else "handler.py"
            payload = {
                "bindings": bindings.get(name, activity_bindings),
                "scriptFile": script_file,
                "disabled": False,
            }
            json.dump(
                payload,
                open(os.path.join(func_dir, "function.json"), "w"),
                indent=2,
            )

        # Copy wrapper files to each activity function directory
        for wrapper_file in wrapper_files:
            src_path = os.path.join(directory, wrapper_file)
            if not os.path.exists(src_path):
                continue
            for func_dir in func_dirs:
                dst_path = os.path.join(func_dir, wrapper_file)
                shutil.copyfile(src_path, dst_path)
            os.remove(src_path)

        # Create __init__.py in each function directory so relative imports work
        for func_dir in func_dirs:
            init_path = os.path.join(func_dir, "__init__.py")
            if not os.path.exists(init_path):
                open(init_path, "w").close()

        task_hub_hash = hashlib.md5()
        for root, dirs, files in os.walk(directory):
            dirs[:] = sorted(dirs)
            for file in sorted(files):
                if file == "host.json" or file.endswith(".zip"):
                    continue
                if ".python_packages" in os.path.relpath(root, directory).split(os.sep):
                    continue
                if not (
                    file.endswith(".py") or file.endswith(".json") or file == "requirements.txt"
                ):
                    continue
                path = os.path.join(root, file)
                rel_path = os.path.relpath(path, directory)
                task_hub_hash.update(rel_path.encode("utf-8"))
                task_hub_hash.update(b"\0")
                with open(path, "rb") as fp:
                    task_hub_hash.update(fp.read())
                task_hub_hash.update(b"\0")
        durable_task_config: Dict[str, object] = {
            "hubName": "sebs" + task_hub_hash.hexdigest()[:16],
        }

        # generate host.json
        host_json = {
            "version": "2.0",
            "extensionBundle": {
                "id": "Microsoft.Azure.Functions.ExtensionBundle",
                "version": "[2.*, 3.0.0)",
            },
            "extensions": {
                "durableTask": durable_task_config,
            },
        }
        json.dump(host_json, open(os.path.join(directory, "host.json"), "w"), indent=2)

        code_size = Benchmark.directory_size(directory)
        execute("zip -qu -r9 {}.zip * .".format(benchmark), shell=True, cwd=directory)
        return directory, code_size

    def _wait_for_function_ready(self, url: str, timeout: int = 300, interval: int = 10) -> None:
        """Poll the function URL until it returns a non-empty HTTP response after publish.

        Azure Functions can take up to several minutes to become available
        after a fresh publish. This method polls until the app responds.

        Args:
            url: The function HTTP trigger URL to probe
            timeout: Maximum seconds to wait (default 300)
            interval: Seconds between probe attempts (default 10)
        """
        import pycurl
        from io import BytesIO

        self.logging.info(f"Waiting for function app to be ready at {url}...")
        deadline = time.time() + timeout
        probe_payload = json.dumps({"request_id": "warmup", "payload": {}})

        while time.time() < deadline:
            c = pycurl.Curl()
            c.setopt(pycurl.URL, url)
            c.setopt(pycurl.POST, 1)
            c.setopt(pycurl.HTTPHEADER, ["Content-Type: application/json"])
            c.setopt(pycurl.POSTFIELDS, probe_payload)
            c.setopt(pycurl.TIMEOUT, 30)
            data = BytesIO()
            c.setopt(pycurl.WRITEFUNCTION, data.write)
            try:
                c.perform()
                if len(data.getvalue()) > 0:
                    self.logging.info("Function app is ready.")
                    return
            except Exception:
                pass
            finally:
                c.close()
            self.logging.info(f"Function app not ready yet, retrying in {interval}s...")
            time.sleep(interval)

        self.logging.warning(
            f"Function app did not become ready within {timeout}s, proceeding anyway."
        )

    def _execute_cli_with_retry(
        self,
        cmd: str,
        max_retries: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 32.0,
        retryable_errors: Optional[Set[str]] = None,
    ) -> bytes:
        """Execute Azure CLI command with retry logic for transient errors.

        Handles transient CLI errors by retrying with exponential backoff
        and jitter. Specific error patterns can be configured for retry.

        Args:
            cmd: Azure CLI command to execute
            max_retries: Maximum number of retry attempts (default: 5)
            base_delay: Base delay in seconds for exponential backoff (default: 1.0)
            max_delay: Maximum delay between retries in seconds (default: 32.0)
            retryable_errors: Set of error patterns to trigger retries
                             (default: NotFound, TooManyRequests, find app with name)

        Returns:
            Command output as bytes

        Raises:
            RuntimeError: If the command fails with a non-retryable error or after
                         exhausting all retry attempts
        """
        if retryable_errors is None:
            retryable_errors = {
                "NotFound",
                "TooManyRequests",
                "find app with name",
                "ServiceUnavailable",
                "InternalServerError",
            }

        attempt = 0
        last_error = None

        while attempt <= max_retries:
            try:
                result = self.cli_instance.execute(cmd)
                if attempt > 0:
                    self.logging.info(f"CLI command succeeded after {attempt} retries")
                return result
            except RuntimeError as e:
                error_message = str(e)
                last_error = e

                # Check if error is retryable
                is_retryable = any(pattern in error_message for pattern in retryable_errors)

                if not is_retryable:
                    raise

                # Check if we have retries left
                if attempt >= max_retries:
                    self.logging.error(
                        f"Max retries ({max_retries}) exhausted for CLI command, "
                        f"failing with error: {error_message}"
                    )
                    raise

                # Calculate delay with exponential backoff and jitter
                delay = min(base_delay * (2**attempt) + random.uniform(0, 1), max_delay)

                if attempt == 0:
                    self.logging.warning(
                        f"Transient CLI error, retrying (attempt {attempt + 1}/{max_retries}): "
                        f"{error_message[:100]}"
                    )
                else:
                    self.logging.info(
                        f"Retry {attempt + 1}/{max_retries} after {delay:.1f}s backoff"
                    )

                time.sleep(delay)
                attempt += 1

        # This should not be reached, but just in case
        if last_error:
            raise last_error
        raise RuntimeError("Unexpected state in retry logic")

    def publish_function(
        self,
        function: Function,
        code_package: Benchmark,
        container_dest: str,
        repeat_on_failure: bool = False,
    ) -> str:
        """Publish function code to Azure Functions.

        Deploys the packaged function code to Azure Functions using the
        Azure Functions CLI tools. Handles retries with exponential backoff
        and jitter for transient errors. This is useful to handle delays in
        Azure cache updates and service availability issues.

        Args:
            function: Function instance to publish
            code_package: Benchmark code package to deploy
            container_dest: Destination path in the CLI container
            repeat_on_failure: Whether to retry on failure

        Returns:
            URL for invoking the published function.

        Raises:
            RuntimeError: If function publication fails or URL cannot be found.
        """
        self.logging.info("Attempting publish of function {}".format(function.name))

        publish_cmd = (
            f"bash -c 'cd {container_dest} "
            "&& func azure functionapp publish {} --{} --no-build'".format(
                function.name, self.AZURE_RUNTIMES[code_package.language_name]
            )
        )

        # Execute publish command with retry if requested
        if repeat_on_failure:
            ret = self._execute_cli_with_retry(publish_cmd)
        else:
            ret = self.cli_instance.execute(publish_cmd)

        self.logging.debug(f"Function app publish of {function.name}, ret {ret.decode('utf-8')}")

        # Extract URL from publish output
        url = ""
        ret_str = ret.decode("utf-8")
        for line in ret_str.split("\n"):
            if "Invoke url:" in line:
                url = line.split("Invoke url:")[1].strip()
                break

        # Fallback: query function details if URL not found in publish output
        if url == "":
            self.logging.warning(
                "Couldn't find function URL in the publish output: {}".format(ret.decode("utf-8"))
            )
            self.logging.info("Querying function details to retrieve URL")

            resource_group = self.config.resources.resource_group(self.cli_instance)
            entrypoint = "main" if isinstance(function, AzureWorkflow) else "handler"
            query_cmd = (
                f"az functionapp function show --function-name {entrypoint} "
                f"--name {function.name} --resource-group {resource_group}"
            )

            # Use retry for the query as well if repeat_on_failure is enabled
            if repeat_on_failure:
                ret = self._execute_cli_with_retry(query_cmd)
            else:
                ret = self.cli_instance.execute(query_cmd)

            self.logging.debug(f"Function query for {function.name}! Return {ret.decode('utf-8')}")
            try:
                url = json.loads(ret.decode("utf-8"))["invokeUrlTemplate"]
            except json.decoder.JSONDecodeError:
                raise RuntimeError(f"Couldn't find the function URL in {ret.decode('utf-8')}")

        return url

    def update_function(
        self,
        function: Function,
        code_package: Benchmark,
        system_variant: SystemVariant,
        container_uri: str | None,
    ) -> None:
        """Update existing Azure Function with new code.

        Updates an existing Azure Function with new code package,
        including environment variables and function configuration.
        It also ensures an HTTP trigger is correctly associated with
        the function's URL.

        Args:
            function: Function instance to update
            code_package: New benchmark code package
            system_variant: Selected deployment variant
            container_uri: Container URI (unused for Azure)

        Raises:
            NotImplementedError: If container deployment is requested.
        """

        if system_variant.is_container:
            raise NotImplementedError("Container deployment is not supported in Azure")

        assert code_package.has_input_processed

        # Update environment variables first since it has a non-deterministic
        # processing time.
        self.update_envs(function, code_package)

        # Mount code package in Docker instance
        container_dest = self._mount_function_code(code_package)
        function_url = self.publish_function(function, code_package, container_dest, True)

        if isinstance(function, AzureWorkflow):
            self.logging.info("Waiting for workflow function app publish to settle...")
            time.sleep(30)
        else:
            self._wait_for_function_ready(function_url)

        # Avoid duplication of HTTP trigger
        found_trigger = False
        for trigger in function.triggers_all():

            if isinstance(trigger, HTTPTrigger):
                found_trigger = True
                trigger.url = function_url

        if not found_trigger:
            trigger = HTTPTrigger(
                function_url, self.config.resources.data_storage_account(self.cli_instance)
            )
            trigger.logging_handlers = self.logging_handlers
            function.add_trigger(trigger)

    def update_envs(
        self, function: Function, code_package: Benchmark, env_variables: dict = {}
    ) -> None:
        """Update environment variables for Azure Function.

        Sets up environment variables required for benchmark execution,
        including storage connection strings and NoSQL database credentials.
        Preserves existing environment variables while adding new ones.

        Args:
            function: Function instance to update
            code_package: Benchmark code package with requirements
            env_variables: Additional environment variables to set

        Raises:
            RuntimeError: If environment variable operations fail.
        """
        envs = env_variables.copy()
        if self.config.redis_host:
            envs["REDIS_HOST"] = self.config.redis_host
            if self.config.redis_username:
                envs["REDIS_USERNAME"] = self.config.redis_username
            if self.config.redis_password:
                envs["REDIS_PASSWORD"] = self.config.redis_password
        if code_package.uses_nosql:

            nosql_storage = cast(CosmosDB, self._system_resources.get_nosql_storage())

            # If we use NoSQL, then the handle must be allocated
            _, url, creds = nosql_storage.credentials()
            db = nosql_storage.benchmark_database(code_package.benchmark)
            envs["NOSQL_STORAGE_DATABASE"] = db
            envs["NOSQL_STORAGE_URL"] = url
            envs["NOSQL_STORAGE_CREDS"] = creds

            for original_name, actual_name in nosql_storage.get_tables(
                code_package.benchmark
            ).items():
                envs[f"NOSQL_STORAGE_TABLE_{original_name}"] = actual_name

        if code_package.uses_storage:

            envs["STORAGE_CONNECTION_STRING"] = self.config.resources.data_storage_account(
                self.cli_instance
            ).connection_string

        resource_group = self.config.resources.resource_group(self.cli_instance)
        # Retrieve existing environment variables to prevent accidental overwrite
        if len(envs) > 0:

            try:
                self.logging.info(
                    f"Retrieving existing environment variables for function {function.name}"
                )

                # First read existing properties
                response = self.cli_instance.execute(
                    f"az functionapp config appsettings list --name {function.name} "
                    f" --resource-group {resource_group} "
                )
                old_envs = json.loads(response.decode())

                # Find custom envs and copy them - unless they are overwritten now
                for env in old_envs:

                    # Ignore vars set automatically by Azure
                    found = False
                    for prefix in ["FUNCTIONS_", "WEBSITE_", "APPINSIGHTS_", "Azure"]:
                        if env["name"].startswith(prefix):
                            found = True
                            break

                    # do not overwrite new value
                    if not found and env["name"] not in envs:
                        envs[env["name"]] = env["value"]

            except RuntimeError as e:
                self.logging.error("Failed to retrieve environment variables!")
                self.logging.error(e)
                raise e

        if len(envs) > 0:
            try:
                env_string = ""
                for k, v in envs.items():
                    env_string += f" {shlex.quote(f'{k}={v}')}"

                self.logging.info(f"Exporting environment variables for function {function.name}")
                self.cli_instance.execute(
                    f"az functionapp config appsettings set --name {function.name} "
                    f" --resource-group {resource_group} "
                    f" --settings {env_string} "
                )
                self.logging.info(
                    f"Restarting function {function.name} to apply environment variables"
                )
                self.cli_instance.execute(
                    f"az functionapp restart --name {function.name} "
                    f" --resource-group {resource_group} "
                )
                time.sleep(10)

            except RuntimeError as e:
                self.logging.error("Failed to set environment variable!")
                self.logging.error(e)
                raise e

    def update_function_configuration(self, function: Function, code_package: Benchmark) -> None:
        """Update Azure Function configuration.

        Currently not implemented for Azure Functions as memory and timeout
        configuration is handled at the consumption plan level.

        Args:
            function: Function instance to configure
            code_package: Benchmark code package with requirements
        """
        # FIXME: this does nothing currently - we don't specify timeout
        self.logging.warning(
            "Updating function's memory and timeout configuration is not supported."
        )

    def delete_function(self, func_name: str, function: Dict) -> None:
        """Delete an Azure Function App and its associated storage account.

        Args:
            func_name: Name of the Azure Function App to delete
        """
        self.logging.info(f"Deleting function app {func_name}")

        """
            For Azure, we need to retrieve the associated storage account.
            Each function has its own storage account.
        """
        function_obj = cast(AzureFunction, self.function_type().deserialize(function))

        try:
            self.cli_instance.execute(
                f"az functionapp delete --name {func_name} "
                f"--resource-group {self.config.resources.resource_group(self.cli_instance)}"
            )
            self.logging.info(f"Function app {func_name} deleted successfully")
        except RuntimeError as e:
            self.logging.error(f"Failed to delete the function app {func_name}!")
            raise e

        self.logging.info(
            f"Deleting storage account {function_obj.function_storage.account_name} "
            f"associated with function {func_name}"
        )
        self.config.resources.delete_storage_account(
            self.cli_instance, function_obj.function_storage
        )

    def _mount_function_code(self, code_package: Benchmark) -> str:
        """Mount function code package in Azure CLI container.

        Uploads the function code package to a temporary location in the
        Azure CLI container for deployment operations.

        Args:
            code_package: Benchmark code package to mount

        Returns:
            Path to mounted code in the CLI container.
        """
        dest = os.path.join("/mnt", "function", uuid.uuid4().hex)

        if code_package.code_location is None:
            raise RuntimeError("Code location is not set")

        self.cli_instance.upload_package(code_package.code_location, dest)
        return dest

    def default_function_name(
        self, code_package: Benchmark, resources: Optional[Resources] = None
    ) -> str:
        """Generate default function name for Azure.

        Creates a globally unique function name based on resource ID,
        benchmark name, language, and version. Function app names must
        be globally unique across all of Azure.

        Args:
            code_package: Benchmark code package
            resources: Optional resources (unused)

        Returns:
            Globally unique function name for Azure.
        """
        func_name = (
            "sebs-{}-{}-{}-{}".format(
                self.config.resources.resources_id,
                code_package.benchmark,
                code_package.language_name,
                code_package.language_version,
            )
            .replace(".", "-")
            .replace("_", "-")
        )
        return func_name

    def create_function(
        self,
        code_package: Benchmark,
        func_name: str,
        system_variant: SystemVariant,
        container_uri: str | None,
    ) -> AzureFunction:
        """Create new Azure Function.

        Creates a new Azure Function App and deploys the provided code package.
        Handles function app creation, storage account allocation, and initial
        deployment with proper configuration.

        Args:
            code_package: Benchmark code package to deploy
            func_name: Name for the Azure Function App
            system_variant: Selected deployment variant
            container_uri: Container URI (unused for Azure)

        Returns:
            AzureFunction instance representing the created function.

        Raises:
            NotImplementedError: If container deployment is requested.
            RuntimeError: If function creation fails.
        """

        if system_variant.is_container:
            raise NotImplementedError("Container deployment is not supported in Azure")

        language = code_package.language_name
        language_runtime = self._normalize_runtime_version(language, code_package.language_version)
        # ensure string form is passed to Azure CLI
        language_runtime = str(language_runtime)
        if language == "java" and "." not in language_runtime:
            language_runtime = f"{language_runtime}.0"
        resource_group = self.config.resources.resource_group(self.cli_instance)
        region = self.config.region
        function_cfg = FunctionConfig.from_benchmark(code_package)

        config = {
            "resource_group": resource_group,
            "func_name": func_name,
            "region": region,
            "runtime": self.AZURE_RUNTIMES[language],
            "runtime_version": language_runtime,
        }

        # check if function does not exist
        # no API to verify existence
        try:
            ret = self.cli_instance.execute(
                (
                    " az functionapp config appsettings list "
                    " --resource-group {resource_group} "
                    " --name {func_name} "
                ).format(**config)
            )
            for setting in json.loads(ret.decode()):
                if setting["name"] == "AzureWebJobsStorage":
                    connection_string = setting["value"]
                    elems = [z for y in connection_string.split(";") for z in y.split("=")]
                    account_name = elems[elems.index("AccountName") + 1]
                    function_storage_account = AzureResources.Storage.from_cache(
                        account_name, connection_string
                    )
            self.logging.info("Azure: Selected {} function app".format(func_name))
        except RuntimeError:
            function_storage_account = self.config.resources.add_storage_account(self.cli_instance)
            config["storage_account"] = function_storage_account.account_name
            # FIXME: only Linux type is supported
            while True:
                try:
                    # create function app
                    ret = self.cli_instance.execute(
                        (
                            " az functionapp create --resource-group {resource_group} "
                            " --os-type Linux --consumption-plan-location {region} "
                            " --runtime {runtime} --runtime-version {runtime_version} "
                            " --name {func_name} --storage-account {storage_account}"
                            " --functions-version 4 "
                        ).format(**config)
                    )
                    self.logging.debug(f"Function app {func_name}, ret {ret.decode('utf-8')}")
                    self.logging.info("Azure: Created function app {}".format(func_name))
                    break
                except RuntimeError as e:
                    # Azure does not allow some concurrent operations
                    if "another operation is in progress" in str(e):
                        self.logging.info(
                            f"Repeat {func_name} creation, another operation in progress"
                        )
                    # Rethrow -> another error
                    else:
                        raise e from None
        function = AzureFunction(
            name=func_name,
            benchmark=code_package.benchmark,
            code_hash=code_package.hash,
            function_storage=function_storage_account,
            cfg=function_cfg,
        )

        # update existing function app
        self.update_function(function, code_package, system_variant, container_uri)

        self.cache_client.add_function(
            deployment_name=self.name(),
            language_name=language,
            code_package=code_package,
            function=function,
        )
        return function

    def cached_function(self, function: Function) -> None:
        """Initialize cached function with current configuration.

        Sets up a cached function with current data storage account
        and logging handlers for all triggers.

        Args:
            function: Function instance loaded from cache
        """
        data_storage_account = self.config.resources.data_storage_account(self.cli_instance)
        for trigger in function.triggers_all():
            azure_trigger = cast(AzureTrigger, trigger)
            azure_trigger.logging_handlers = self.logging_handlers
            azure_trigger.data_storage_account = data_storage_account

    def create_workflow(
        self,
        code_package: Benchmark,
        workflow_name: str,
        container_uri: str | None = None,
    ) -> AzureWorkflow:
        """Create a new Azure Durable Functions workflow.

        Deploys the workflow as a single Function App containing the
        orchestrator, sub-orchestrator, and all activity functions.

        Args:
            code_package: Benchmark code package with workflow definition
            workflow_name: Name for the workflow Function App

        Returns:
            AzureWorkflow instance representing the deployed workflow.
        """
        language = code_package.language_name
        language_runtime = self._normalize_runtime_version(language, code_package.language_version)
        language_runtime = str(language_runtime)
        resource_group = self.config.resources.resource_group(self.cli_instance)
        region = self.config.region
        function_cfg = FunctionConfig.from_benchmark(code_package)

        config = {
            "resource_group": resource_group,
            "func_name": workflow_name,
            "region": region,
            "runtime": self.AZURE_RUNTIMES[language],
            "runtime_version": language_runtime,
            "plan_args": f"--consumption-plan-location {region}",
            "os_args": "--os-type Linux",
        }

        # Check if function app already exists
        function_storage_account: Optional[AzureResources.Storage] = None
        try:
            ret = self.cli_instance.execute(
                (
                    " az functionapp config appsettings list "
                    " --resource-group {resource_group} "
                    " --name {func_name} "
                ).format(**config)
            )
        except RuntimeError:
            ret = None

        if ret is not None:
            for setting in json.loads(ret.decode()):
                if setting["name"] == "AzureWebJobsStorage":
                    connection_string = setting["value"]
                    elems = [z for y in connection_string.split(";") for z in y.split("=")]
                    account_name = elems[elems.index("AccountName") + 1]
                    function_storage_account = AzureResources.Storage.from_cache(
                        account_name, connection_string
                    )
            assert function_storage_account is not None
            self.logging.info("Azure: Selected existing workflow app {}".format(workflow_name))

        if function_storage_account is None:
            function_storage_account = self.config.resources.add_storage_account(self.cli_instance)
            config["storage_account"] = function_storage_account.account_name
            while True:
                try:
                    self.cli_instance.execute(
                        (
                            " az functionapp create --resource-group {resource_group} "
                            " {os_args} {plan_args} "
                            " --runtime {runtime} --runtime-version {runtime_version} "
                            " --name {func_name} --storage-account {storage_account}"
                            " --functions-version 4 "
                        ).format(**config)
                    )
                    self.logging.info("Azure: Created workflow app {}".format(workflow_name))
                    break
                except RuntimeError as e:
                    if "another operation is in progress" in str(e):
                        self.logging.info(
                            f"Repeat {workflow_name} creation, another operation in progress"
                        )
                    else:
                        raise e from None

        workflow = AzureWorkflow(
            name=workflow_name,
            benchmark=code_package.benchmark,
            code_hash=code_package.hash,
            function_storage=function_storage_account,
            cfg=function_cfg,
        )

        self.update_function(workflow, code_package, code_package.system_variant, None)

        self.cache_client.add_function(
            deployment_name=self.name(),
            language_name=language,
            code_package=code_package,
            function=workflow,
        )
        return workflow

    def update_workflow(
        self,
        workflow: Workflow,
        code_package: Benchmark,
        container_uri: str | None = None,
    ) -> None:
        """Update an existing Azure Durable Functions workflow.

        Args:
            workflow: Workflow instance to update
            code_package: New benchmark code package
        """
        self.update_function(workflow, code_package, code_package.system_variant, None)

    def refresh_workflow_configuration(self, workflow: Workflow, code_package: Benchmark) -> bool:
        """Refresh runtime configuration for a cached Azure workflow."""
        if self.config.redis_host and code_package.has_input_processed:
            self.update_envs(workflow, code_package)
            return True
        return False

    def download_metrics(
        self,
        function_name: str,
        start_time: int,
        end_time: int,
        requests: Dict[str, ExecutionResult],
        metrics: Dict[str, dict],
    ) -> None:
        """Download execution metrics from Azure Application Insights.

        Retrieves performance metrics for function executions from Azure
        Application Insights and updates the execution results with
        provider-specific timing information.

        Args:
            function_name: Name of the Azure Function
            start_time: Start timestamp for metrics collection
            end_time: End timestamp for metrics collection
            requests: Dictionary of execution results to update
            metrics: Additional metrics dictionary (unused)
        """

        self.cli_instance.install_insights()

        resource_group = self.config.resources.resource_group(self.cli_instance)
        # Avoid warnings in the next step
        self.cli_instance.execute(
            "az feature register --name AIWorkspacePreview " "--namespace microsoft.insights"
        )
        app_id_query = self.cli_instance.execute(
            ("az monitor app-insights component show " "--app {} --resource-group {}").format(
                function_name, resource_group
            )
        ).decode("utf-8")
        application_id = json.loads(app_id_query)["appId"]

        # Azure CLI requires date in the following format
        # Format: date (yyyy-mm-dd) time (hh:mm:ss.xxxxx) timezone (+/-hh:mm)
        # Include microseconds time to make sure we're not affected by
        # miliseconds precision.
        start_time_str = datetime.datetime.fromtimestamp(start_time).strftime(
            "%Y-%m-%d %H:%M:%S.%f"
        )
        end_time_str = datetime.datetime.fromtimestamp(end_time + 1).strftime("%Y-%m-%d %H:%M:%S")
        from tzlocal import get_localzone

        timezone_str = datetime.datetime.now(get_localzone()).strftime("%z")

        query = (
            "requests | project timestamp, operation_Name, success, "
            "resultCode, duration, cloud_RoleName, "
            "invocationId=customDimensions['InvocationId'], "
            "functionTime=customDimensions['FunctionExecutionTimeMs']"
        )
        invocations_processed: Set[str] = set()
        invocations_to_process = set(requests.keys())
        # while len(invocations_processed) < len(requests.keys()):
        self.logging.info("Azure: Running App Insights query.")
        ret_bytes = self.cli_instance.execute(
            (
                'az monitor app-insights query --app {} --analytics-query "{}" '
                "--start-time {} {} --end-time {} {}"
            ).format(
                application_id,
                query,
                start_time_str,
                timezone_str,
                end_time_str,
                timezone_str,
            )
        )
        ret_str = ret_bytes.decode("utf-8")
        json_data = json.loads(ret_str)
        table_data = json_data["tables"][0]
        # time is last, invocation is second to last
        for request in table_data["rows"]:
            invocation_id = request[-2]
            # might happen that we get invocation from another experiment
            if invocation_id not in requests:
                continue
            # duration = request[4]
            func_exec_time = request[-1]
            invocations_processed.add(invocation_id)
            requests[invocation_id].provider_times.execution = int(float(func_exec_time) * 1000)
        self.logging.info(
            f"Azure: Found time metrics for {len(invocations_processed)} "
            f"out of {len(requests.keys())} invocations."
        )
        if len(invocations_processed) < len(requests.keys()):
            time.sleep(5)
        self.logging.info(f"Missing the requests: {invocations_to_process - invocations_processed}")

        # TODO: query performance counters for mem

    def _enforce_cold_start(self, function: Function, code_package: Benchmark) -> None:
        """Enforce cold start for a single function.

        Updates environment variable to force cold start behavior.

        Args:
            function: Function instance to update
            code_package: Benchmark code package
        """
        self.update_envs(function, code_package, {"ForceColdStart": str(self.cold_start_counter)})

        # FIXME: is this sufficient to enforce cold starts?
        # self.update_function(function, code_package, False, "")

    def enforce_cold_start(self, functions: List[Function], code_package: Benchmark) -> None:
        """Enforce cold start for multiple functions.

        Forces cold start behavior for all provided functions by updating
        environment variables and waiting for changes to propagate:
        sleep is added to allow changes to propagate.

        Args:
            functions: List of functions to enforce cold start for
            code_package: Benchmark code package
        """
        self.cold_start_counter += 1
        for func in functions:
            self._enforce_cold_start(func, code_package)
        time.sleep(20)

    def create_trigger(self, function: Function, trigger_type: Trigger.TriggerType) -> Trigger:
        """Create trigger for Azure Function.

        HTTP triggers are automatically created during deployment.
        For workflows, LIBRARY trigger requests are satisfied by returning
        the existing HTTP trigger, since Azure Durable Functions uses HTTP.

        Args:
            function: Function to create trigger for
            trigger_type: Type of trigger to create

        Returns:
            The HTTP trigger for this function.

        Raises:
            NotImplementedError: If no HTTP trigger exists on the function.
        """
        from sebs.azure.function import AzureWorkflow
        from sebs.azure.triggers import WorkflowHTTPTrigger

        http_triggers = function.triggers(Trigger.TriggerType.HTTP)
        if trigger_type == Trigger.TriggerType.LIBRARY and isinstance(function, AzureWorkflow):
            library_triggers = function.triggers(Trigger.TriggerType.LIBRARY)
            if library_triggers:
                return library_triggers[0]
            if http_triggers:
                http_trigger = cast(HTTPTrigger, http_triggers[0])
                trigger = WorkflowHTTPTrigger(
                    http_trigger.url,
                    self.config.resources.data_storage_account(self.cli_instance),
                )
                trigger.logging_handlers = self.logging_handlers
                function.add_trigger(trigger)
                self.cache_client.update_function(function)
                return trigger

        if trigger_type == Trigger.TriggerType.HTTP and http_triggers:
            return http_triggers[0]
        raise NotImplementedError()
