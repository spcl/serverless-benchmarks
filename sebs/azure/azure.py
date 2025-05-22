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
    logs_client = None
    storage: BlobStorage
    cached = False
    _config: AzureConfig

    # runtime mapping
    AZURE_RUNTIMES = {"python": "python", "nodejs": "node"}

    @staticmethod
    def name():
        """Return the name of the cloud provider (azure)."""
        return "azure"

    @property
    def config(self) -> AzureConfig:
        """Return the Azure-specific configuration."""
        return self._config

    @staticmethod
    def function_type() -> Type[Function]:
        """Return the type of the function implementation for Azure."""
        return AzureFunction

    @property
    def cli_instance(self) -> AzureCLI:
        """Return the Azure CLI instance."""
        return cast(AzureSystemResources, self._system_resources).cli_instance

    def __init__(
        self,
        sebs_config: SeBSConfig,
        config: AzureConfig,
        cache_client: Cache,
        docker_client: docker.client,
        logger_handlers: LoggingHandlers,
    ):
        """
        Initialize Azure provider.

        :param sebs_config: SeBS configuration.
        :param config: Azure-specific configuration.
        :param cache_client: Function cache instance.
        :param docker_client: Docker client instance.
        :param logger_handlers: Logging handlers.
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
    ):
        """
        Initialize Azure resources and allocate shared resources.
        Starts the Docker container running Azure CLI tools if not already running.

        :param config: Additional configuration parameters (not used).
        :param resource_prefix: Optional prefix for resource names.
        """
        self.initialize_resources(select_prefix=resource_prefix)
        self.allocate_shared_resource()

    def shutdown(self):
        """Shutdown the Azure provider, including the Azure CLI Docker container."""
        cast(AzureSystemResources, self._system_resources).shutdown()
        super().shutdown()

    def find_deployments(self) -> List[str]:
        """
        Find existing SeBS deployments (resource groups) in Azure.

        Looks for resource groups matching the pattern "sebs_resource_group_(.*)".

        :return: List of deployment identifiers (resource prefixes).
        """
        resource_groups = self.config.resources.list_resource_groups(self.cli_instance)
        deployments = []
        for group in resource_groups:
            # The benchmarks bucket must exist in every deployment.
            deployment_search = re.match("sebs_resource_group_(.*)", group)
            if deployment_search:
                deployments.append(deployment_search.group(1))

        return deployments

    def allocate_shared_resource(self):
        """
        Allocate or retrieve shared resources like the data storage account.

        This allows multiple deployment clients to share the same settings,
        simplifying regression testing.
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
        """
        Package benchmark code for Azure Functions.

        The directory structure for Azure Functions is:
        handler/
            - source files (e.g., benchmark code)
            - Azure wrappers (handler.py/js, storage.py if used)
            - additional resources
            - function.json (bindings configuration)
        host.json (host configuration)
        requirements.txt / package.json (dependencies)

        Python packages are expected to be in .python_packages/ after installation.

        :param directory: Directory containing the benchmark code.
        :param language_name: Name of the programming language.
        :param language_version: Version of the programming language.
        :param architecture: CPU architecture (not used by Azure Functions packaging).
        :param benchmark: Name of the benchmark.
        :param is_cached: Flag indicating if the code is cached (not directly used in packaging logic).
        :param container_deployment: Flag indicating if deploying as a container image (not supported).
        :return: Tuple containing the path to the directory (Azure zips it implicitly),
                 size of the directory in bytes, and an empty container URI string.
        :raises NotImplementedError: If container_deployment is True.
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
        # Azure CLI zips the function code automatically during publish.
        # We return the directory path and its size.
        # The execute command for zipping is not strictly necessary for Azure deployment itself
        # but might be kept for consistency or other internal uses.
        execute("zip -qu -r9 {}.zip * .".format(benchmark), shell=True, cwd=directory)
        return directory, code_size, container_uri

    def publish_function(
        self,
        function: Function,
        code_package: Benchmark,
        container_dest: str,
        repeat_on_failure: bool = False,
    ) -> str:
        """
        Publish function code to Azure Functions.

        Uses Azure CLI (`func azure functionapp publish`) to deploy the code.
        Can repeat on failure, which is useful for delays in Azure cache updates.

        :param function: Function object.
        :param code_package: Benchmark object containing language details.
        :param container_dest: Path within the Azure CLI Docker container where code is mounted.
        :param repeat_on_failure: If True, retry publishing if the function app is not found.
        :return: URL of the published HTTP-triggered function.
        :raises RuntimeError: If publishing fails and repeat_on_failure is False,
                              or if the function URL cannot be retrieved.
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
    ):
        """
        Update an Azure Function with new code and configuration.

        This involves updating environment variables and then publishing the new code package.
        It also ensures an HTTP trigger is correctly associated with the function's URL.

        :param function: Function object to update.
        :param code_package: Benchmark object with new code and configuration.
        :param container_deployment: Flag for container deployment (not supported).
        :param container_uri: Container URI (not used).
        :raises NotImplementedError: If container_deployment is True.
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

    def update_envs(self, function: Function, code_package: Benchmark, env_variables: dict = {}):
        """
        Update environment variables for an Azure Function.

        Sets variables for NoSQL database access (CosmosDB) and Azure Storage
        if the benchmark uses them. Preserves existing non-SeBS managed variables.

        :param function: Function object.
        :param code_package: Benchmark object.
        :param env_variables: Additional environment variables to set/override.
        :raises RuntimeError: If retrieving or setting environment variables fails.
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

    def update_function_configuration(self, function: Function, code_package: Benchmark):
        """
        Update function's memory and timeout configuration.

        Note: Currently, this is not supported for Azure Functions via SeBS.
        A warning is logged.

        :param function: Function object.
        :param code_package: Benchmark object.
        """
        # FIXME: this does nothing currently - we don't specify timeout
        self.logging.warning(
            "Updating function's memory and timeout configuration is not supported."
        )

    def _mount_function_code(self, code_package: Benchmark) -> str:
        """
        Mount the function code package into the Azure CLI Docker container.

        Generates a unique destination path within the container's /mnt/function directory.

        :param code_package: Benchmark object containing the code location.
        :return: Destination path within the Docker container.
        """
        dest = os.path.join("/mnt", "function", uuid.uuid4().hex)
        self.cli_instance.upload_package(code_package.code_location, dest)
        return dest

    def default_function_name(
        self, code_package: Benchmark, resources: Optional[Resources] = None
    ) -> str:
        """
        Generate a default function name for Azure Functions.

        Function app names must be globally unique in Azure.
        The name is constructed using SeBS prefix, resource ID, benchmark name,
        language, and version, with dots and underscores replaced by hyphens.

        :param code_package: Benchmark object.
        :param resources: Optional Resources object (uses self.config.resources if None).
        :return: Default function name string.
        """
        current_resources = resources if resources else self.config.resources
        func_name = (
            "sebs-{}-{}-{}-{}".format(
                current_resources.resources_id,
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
        """
        Create or update an Azure Function app.

        If the function app doesn't exist, it's created with necessary configurations
        (resource group, storage account, runtime). Then, the function code is deployed.
        If it exists, it's updated.

        :param code_package: Benchmark object.
        :param func_name: Desired name for the function app.
        :param container_deployment: Flag for container deployment (not supported).
        :param container_uri: Container URI (not used).
        :return: AzureFunction object.
        :raises NotImplementedError: If container_deployment is True.
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

    def cached_function(self, function: Function):
        """
        Configure a cached Azure Function instance.

        Sets up logging handlers and the data storage account for its triggers.

        :param function: Function object (expected to be AzureFunction).
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
    ):
        """
        Download invocation metrics from Azure Application Insights.

        Queries App Insights for request logs and custom dimensions (like FunctionExecutionTimeMs)
        to populate ExecutionResult objects.

        :param function_name: Name of the Azure Function app.
        :param start_time: Start timestamp for querying logs.
        :param end_time: End timestamp for querying logs.
        :param requests: Dictionary of request IDs to ExecutionResult objects.
        :param metrics: Dictionary to store additional metrics (not directly used here).
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

    def _enforce_cold_start(self, function: Function, code_package: Benchmark):
        """
        Helper method to enforce a cold start for a single Azure Function.

        Updates function environment variables with a unique 'ForceColdStart' value.
        Note: The effectiveness of this method for ensuring cold starts might depend
        on Azure's internal behavior and caching. The commented-out `update_function`
        call suggests that simply updating envs might not always be sufficient.

        :param function: Function object.
        :param code_package: Benchmark object.
        """
        self.update_envs(function, code_package, {"ForceColdStart": str(self.cold_start_counter)})

        # FIXME: is this sufficient to enforce cold starts?
        # self.update_function(function, code_package, False, "")

    def enforce_cold_start(self, functions: List[Function], code_package: Benchmark):
        """
        Enforce cold starts for a list of Azure Functions.

        Increments a counter and updates function configurations to attempt
        to ensure the next invocation is a cold start. A sleep is added to allow
        changes to propagate.

        :param functions: List of Function objects.
        :param code_package: Benchmark object.
        """
        self.cold_start_counter += 1
        for func in functions:
            self._enforce_cold_start(func, code_package)
        import time

        time.sleep(20)

    def create_trigger(self, function: Function, trigger_type: Trigger.TriggerType) -> Trigger:
        """
        Create a trigger for an Azure Function.

        Note: This method is not currently implemented. HTTP triggers are typically
        created and managed during the function deployment and update process.

        :param function: Function object.
        :param trigger_type: Type of trigger to create.
        :raises NotImplementedError: This method is not yet implemented for Azure.
        """
        raise NotImplementedError()


#
#    def create_azure_function(self, fname, config):
#
#        # create function name
#        region = self.config["config"]["region"]
#        # only hyphens are allowed
#        # and name needs to be globally unique
#        func_name = fname.replace(".", "-").replace("_", "-")
#
#        # create function app
#        self.cli_instance.execute(
#            (
#                "az functionapp create --resource-group {} "
#                "--os-type Linux --consumption-plan-location {} "
#                "--runtime {} --runtime-version {} --name {} "
#                "--storage-account {}"
#            ).format(
#                self.resource_group_name,
#                region,
#                self.AZURE_RUNTIMES[self.language],
#                self.config["config"]["runtime"][self.language],
#                func_name,
#                self.storage_account_name,
#            )
#        )
#        logging.info("Created function app {}".format(func_name))
#        return func_name
#
#    init = False
#
#    def create_function_copies(
#        self,
#        function_names: List[str],
#        code_package: Benchmark,
#        experiment_config: dict,
#    ):
#
#        if not self.init:
#            code_location = code_package.code_location
#            # package = self.package_code(code_location, code_package.benchmark)
#            # code_size = code_package.code_size
#            # Restart Docker instance to make sure code package is mounted
#            self.start(code_location, restart=True)
#            self.storage_account()
#            self.resource_group()
#            self.init = True
#
#        # names = []
#        # for fname in function_names:
#        #    names.append(self.create_azure_function(fname, experiment_config))
#        names = function_names
#
#        # time.sleep(30)
#        urls = []
#        for fname in function_names:
#            url = self.publish_function(fname, repeat_on_failure=True)
#            urls.append(url)
#            logging.info("Published function app {} with URL {}".format(fname, url))
#
#        return names, urls
