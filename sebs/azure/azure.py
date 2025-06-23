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
    Basic usage for Azure benchmarking:
    
    ```python
    from sebs.azure.azure import Azure
    from sebs.azure.config import AzureConfig
    
    # Initialize Azure system with configuration
    azure_system = Azure(sebs_config, azure_config, cache, docker_client, handlers)
    azure_system.initialize()
    
    # Deploy and benchmark functions
    function = azure_system.create_function(code_package, func_name, False, "")
    result = function.invoke(payload)
    ```
"""

import datetime
import json
import re
import os
import shutil
import time
import uuid
from typing import cast, Dict, List, Optional, Set, Tuple, Type  # noqa

import docker

from sebs.azure.blob_storage import BlobStorage
from sebs.azure.cli import AzureCLI
from sebs.azure.cosmosdb import CosmosDB
from sebs.azure.function import AzureFunction
from sebs.azure.config import AzureConfig, AzureResources
from sebs.azure.system_resources import AzureSystemResources
from sebs.azure.triggers import AzureTrigger, HTTPTrigger
from sebs.faas.function import Trigger
from sebs.benchmark import Benchmark
from sebs.cache import Cache
from sebs.config import SeBSConfig
from sebs.utils import LoggingHandlers, execute
from sebs.faas.function import Function, FunctionConfig, ExecutionResult
from sebs.faas.system import System
from sebs.faas.config import Resources


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
    AZURE_RUNTIMES = {"python": "python", "nodejs": "node"}

    @staticmethod
    def name() -> str:
        """Get the platform name.

        Returns:
            Platform name 'azure'.
        """
        return "azure"

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
        docker_client: docker.client,
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
    ) -> None:
        """Initialize Azure system and start CLI container.

        Initializes Azure resources and allocates shared resources like
        data storage account. Starts the Docker container with Azure CLI tools.

        Args:
            config: Additional configuration parameters
            resource_prefix: Optional prefix for resource naming
        """
        self.initialize_resources(select_prefix=resource_prefix)
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
        to identify existing deployments that can be reused.

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
        language_name: str,
        language_version: str,
        architecture: str,
        benchmark: str,
        is_cached: bool,
        container_deployment: bool,
    ) -> Tuple[str, int, str]:
        """Package function code for Azure Functions deployment.

        Creates the proper directory structure and configuration files
        required for Azure Functions deployment. The structure includes:
        - handler/ directory with source files and Azure wrappers
        - function.json with trigger and binding configuration
        - host.json with runtime configuration
        - requirements.txt or package.json with dependencies

        Args:
            directory: Directory containing the function code
            language_name: Programming language (python, nodejs)
            language_version: Language runtime version
            architecture: Target architecture (currently unused)
            benchmark: Name of the benchmark
            is_cached: Whether the package is from cache
            container_deployment: Whether to use container deployment

        Returns:
            Tuple of (directory_path, code_size_bytes, container_uri)

        Raises:
            NotImplementedError: If container deployment is requested.
        """

        container_uri = ""

        if container_deployment:
            raise NotImplementedError("Container Deployment is not supported in Azure")

        # In previous step we ran a Docker container which installed packages
        # Python packages are in .python_packages because this is expected by Azure
        EXEC_FILES = {"python": "handler.py", "nodejs": "handler.js"}
        CONFIG_FILES = {
            "python": ["requirements.txt", ".python_packages"],
            "nodejs": ["package.json", "node_modules"],
        }
        package_config = CONFIG_FILES[language_name]

        handler_dir = os.path.join(directory, "handler")
        os.makedirs(handler_dir)
        # move all files to 'handler' except package config
        for f in os.listdir(directory):
            if f not in package_config:
                source_file = os.path.join(directory, f)
                shutil.move(source_file, handler_dir)

        # generate function.json
        # TODO: extension to other triggers than HTTP
        default_function_json = {
            "scriptFile": EXEC_FILES[language_name],
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
        return directory, code_size, container_uri

    def publish_function(
        self,
        function: Function,
        code_package: Benchmark,
        container_dest: str,
        repeat_on_failure: bool = False,
    ) -> str:
        """Publish function code to Azure Functions.

        Deploys the packaged function code to Azure Functions using the
        Azure Functions CLI tools. Handles retries and URL extraction.

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
        success = False
        url = ""
        self.logging.info("Attempting publish of function {}".format(function.name))
        while not success:
            try:
                ret = self.cli_instance.execute(
                    f"bash -c 'cd {container_dest} "
                    "&& func azure functionapp publish {} --{} --no-build'".format(
                        function.name, self.AZURE_RUNTIMES[code_package.language_name]
                    )
                )
                url = ""
                for line in ret.split(b"\n"):
                    line = line.decode("utf-8")
                    if "Invoke url:" in line:
                        url = line.split("Invoke url:")[1].strip()
                        break

                # We failed to find the URL the normal way
                # Sometimes, the output does not include functions.
                if url == "":
                    self.logging.warning(
                        "Couldnt find function URL in the output: {}".format(ret.decode("utf-8"))
                    )

                    self.logging.info("Sleeping 30 seconds before attempting another query.")

                    resource_group = self.config.resources.resource_group(self.cli_instance)
                    ret = self.cli_instance.execute(
                        "az functionapp function show --function-name handler "
                        f"--name {function.name} --resource-group {resource_group}"
                    )
                    try:
                        url = json.loads(ret.decode("utf-8"))["invokeUrlTemplate"]
                    except json.decoder.JSONDecodeError:
                        raise RuntimeError(
                            f"Couldn't find the function URL in {ret.decode('utf-8')}"
                        )

                success = True
            except RuntimeError as e:
                error = str(e)
                # app not found
                # Azure changed the description as some point
                if ("find app with name" in error or "NotFound" in error) and repeat_on_failure:
                    # Sleep because of problems when publishing immediately
                    # after creating function app.
                    time.sleep(30)
                    self.logging.info(
                        "Sleep 30 seconds for Azure to register function app {}".format(
                            function.name
                        )
                    )
                # escape loop. we failed!
                else:
                    raise e
        return url

    def update_function(
        self,
        function: Function,
        code_package: Benchmark,
        container_deployment: bool,
        container_uri: str,
    ) -> None:
        """Update existing Azure Function with new code.

        Updates an existing Azure Function with new code package,
        including environment variables and function configuration.

        Args:
            function: Function instance to update
            code_package: New benchmark code package
            container_deployment: Whether using container deployment
            container_uri: Container URI (unused for Azure)

        Raises:
            NotImplementedError: If container deployment is requested.
        """

        if container_deployment:
            raise NotImplementedError("Container deployment is not supported in Azure")

        assert code_package.has_input_processed

        # Update environment variables first since it has a non-deterministic
        # processing time.
        self.update_envs(function, code_package)

        # Mount code package in Docker instance
        container_dest = self._mount_function_code(code_package)
        function_url = self.publish_function(function, code_package, container_dest, True)

        # Avoid duplication of HTTP trigger
        found_trigger = False
        for trigger in function.triggers_all():

            if isinstance(trigger, HTTPTrigger):
                found_trigger = True
                trigger.url = function_url
                break

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
        envs = {}
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
                    env_string += f" {k}={v}"

                self.logging.info(f"Exporting environment variables for function {function.name}")
                self.cli_instance.execute(
                    f"az functionapp config appsettings set --name {function.name} "
                    f" --resource-group {resource_group} "
                    f" --settings {env_string} "
                )

                # if we don't do that, next invocation might still see old values
                # Disabled since we swapped the order - we first update envs, then we publish.
                # self.logging.info(
                #    "Sleeping for 10 seconds - Azure needs more time to propagate changes. "
                #    "Otherwise, functions might not see new variables and fail unexpectedly."
                # )

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
        container_deployment: bool,
        container_uri: str,
    ) -> AzureFunction:
        """Create new Azure Function.

        Creates a new Azure Function App and deploys the provided code package.
        Handles function app creation, storage account allocation, and initial
        deployment with proper configuration.

        Args:
            code_package: Benchmark code package to deploy
            func_name: Name for the Azure Function App
            container_deployment: Whether to use container deployment
            container_uri: Container URI (unused for Azure)

        Returns:
            AzureFunction instance representing the created function.

        Raises:
            NotImplementedError: If container deployment is requested.
            RuntimeError: If function creation fails.
        """

        if container_deployment:
            raise NotImplementedError("Container deployment is not supported in Azure")

        language = code_package.language_name
        language_runtime = code_package.language_version
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
                    self.cli_instance.execute(
                        (
                            " az functionapp create --resource-group {resource_group} "
                            " --os-type Linux --consumption-plan-location {region} "
                            " --runtime {runtime} --runtime-version {runtime_version} "
                            " --name {func_name} --storage-account {storage_account}"
                            " --functions-version 4 "
                        ).format(**config)
                    )
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
                        raise
        function = AzureFunction(
            name=func_name,
            benchmark=code_package.benchmark,
            code_hash=code_package.hash,
            function_storage=function_storage_account,
            cfg=function_cfg,
        )

        # update existing function app
        self.update_function(function, code_package, container_deployment, container_uri)

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
        ret = self.cli_instance.execute(
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
        ret = self.cli_instance.execute(
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
        ).decode("utf-8")
        ret = json.loads(ret)
        ret = ret["tables"][0]
        # time is last, invocation is second to last
        for request in ret["rows"]:
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
        environment variables and waiting for changes to propagate.

        Args:
            functions: List of functions to enforce cold start for
            code_package: Benchmark code package
        """
        self.cold_start_counter += 1
        for func in functions:
            self._enforce_cold_start(func, code_package)
        import time

        time.sleep(20)

    def create_trigger(self, function: Function, trigger_type: Trigger.TriggerType) -> Trigger:
        """Create trigger for Azure Function.

        Currently not implemented as HTTP triggers are automatically
        created for each function during deployment.

        Args:
            function: Function to create trigger for
            trigger_type: Type of trigger to create

        Raises:
            NotImplementedError: Trigger creation is not supported.
        """
        raise NotImplementedError()
