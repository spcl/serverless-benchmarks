import datetime
import json
import re
import os
import shutil
import time
import uuid
from typing import cast, Dict, List, Optional, Set, Tuple, Type, TypeVar  # noqa

import docker

from sebs.azure.blob_storage import BlobStorage
from sebs.azure.cli import AzureCLI
from sebs.azure.function import AzureFunction, AzureWorkflow
from sebs.azure.config import AzureConfig, AzureResources
from sebs.azure.triggers import AzureTrigger, HTTPTrigger
from sebs.benchmark import Benchmark
from sebs.cache import Cache
from sebs.config import SeBSConfig
from sebs.utils import LoggingHandlers, execute, replace_string_in_file
from sebs.faas.function import (
    CloudBenchmark,
    FunctionConfig,
    Function,
    ExecutionResult,
    Workflow,
    Trigger,
)
from sebs.faas.storage import PersistentStorage
from sebs.faas.system import System


class Azure(System):
    logs_client = None
    storage: BlobStorage
    cached = False
    _config: AzureConfig

    # runtime mapping
    AZURE_RUNTIMES = {"python": "python", "nodejs": "node"}

    @staticmethod
    def name():
        return "azure"

    @property
    def config(self) -> AzureConfig:
        return self._config

    @staticmethod
    def function_type() -> Type[Function]:
        return AzureFunction

    @staticmethod
    def workflow_type() -> Type[Workflow]:
        return AzureWorkflow

    def __init__(
        self,
        sebs_config: SeBSConfig,
        config: AzureConfig,
        cache_client: Cache,
        docker_client: docker.client,
        logger_handlers: LoggingHandlers,
    ):
        super().__init__(sebs_config, cache_client, docker_client)
        self.logging_handlers = logger_handlers
        self._config = config

    def initialize_cli(self, cli: AzureCLI):
        self.cli_instance = cli
        self.cli_instance_stop = False

    """
        Start the Docker container running Azure CLI tools.
    """

    def initialize(
        self,
        config: Dict[str, str] = {},
        resource_prefix: Optional[str] = None,
    ):
        if not hasattr(self, "cli_instance"):
            self.cli_instance = AzureCLI(self.system_config, self.docker_client)
            self.cli_instance_stop = True

        output = self.cli_instance.login(
            appId=self.config.credentials.appId,
            tenant=self.config.credentials.tenant,
            password=self.config.credentials.password,
        )

        subscriptions = json.loads(output)
        if len(subscriptions) == 0:
            raise RuntimeError("Didn't find any valid subscription on Azure!")
        if len(subscriptions) > 1:
            raise RuntimeError("Found more than one valid subscription on Azure - not supported!")

        self.config.credentials.subscription_id = subscriptions[0]["id"]

        self.initialize_resources(select_prefix=resource_prefix)
        self.allocate_shared_resource()

    def shutdown(self):
        if self.cli_instance and self.cli_instance_stop:
            self.cli_instance.shutdown()
        super().shutdown()

    def find_deployments(self) -> List[str]:

        """
        Look for duplicated resource groups.
        """
        resource_groups = self.config.resources.list_resource_groups(self.cli_instance)
        deployments = []
        for group in resource_groups:
            # The benchmarks bucket must exist in every deployment.
            deployment_search = re.match("sebs_resource_group_(.*)", group)
            if deployment_search:
                deployments.append(deployment_search.group(1))

        return deployments

    """
        Allow multiple deployment clients share the same settings.
        Not an ideal situation, but makes regression testing much simpler.
    """

    def allocate_shared_resource(self):
        self.config.resources.data_storage_account(self.cli_instance)

    """
        Create wrapper object for Azure blob storage.
        First ensure that storage account is created and connection string
        is known. Then, create wrapper and create request number of buckets.

        Requires Azure CLI instance in Docker to obtain storage account details.

        :param benchmark:
        :param buckets: number of input and output buckets
        :param replace_existing: when true, replace existing files in input buckets
        :return: Azure storage instance
    """

    def get_storage(self, replace_existing: bool = False) -> PersistentStorage:
        if not hasattr(self, "storage"):
            self.storage = BlobStorage(
                self.config.region,
                self.cache_client,
                self.config.resources,
                self.config.resources.data_storage_account(self.cli_instance).connection_string,
                replace_existing=replace_existing,
            )
            self.storage.logging_handlers = self.logging_handlers
        else:
            self.storage.replace_existing = replace_existing
        return self.storage

    # Directory structure
    # handler
    # - source files
    # - Azure wrappers - handler, storage
    # - additional resources
    # - function.json
    # host.json
    # requirements.txt/package.json
    def package_code(
        self, code_package: Benchmark, directory: str, is_workflow: bool, is_cached: bool
    ) -> Tuple[str, int]:

        # In previous step we ran a Docker container which installed packages
        # Python packages are in .python_packages because this is expected by Azure
        FILES = {"python": "*.py", "nodejs": "*.js"}
        CONFIG_FILES = {
            "python": ["requirements.txt", ".python_packages"],
            "nodejs": ["package.json", "node_modules"],
        }
        WRAPPER_FILES = {
            "python": ["handler.py", "storage.py", "fsm.py"],
            "nodejs": ["handler.js", "storage.js"],
        }
        file_type = FILES[code_package.language_name]
        package_config = CONFIG_FILES[code_package.language_name]
        wrapper_files = WRAPPER_FILES[code_package.language_name]

        print(directory)

        if is_workflow:

            main_path = os.path.join(directory, "main_workflow.py")
            os.rename(main_path, os.path.join(directory, "main.py"))

            # Make sure we have a valid workflow benchmark
            src_path = os.path.join(code_package.benchmark_path, "definition.json")
            if not os.path.exists(src_path):
                raise ValueError(f"No workflow definition found in {directory}")

            dst_path = os.path.join(directory, "definition.json")
            shutil.copy2(src_path, dst_path)

        else:
            # Put function's resources inside a dedicated directory
            os.mkdir(os.path.join(directory, "function"))
            for path in os.listdir(directory):

                if path in [
                    "main_workflow.py",
                    "run_workflow.py",
                    "run_subworkflow",
                    "fsm.py",
                    ".python_packages",
                ]:
                    continue

                shutil.move(os.path.join(directory, path), os.path.join(directory, "function"))

            main_path = os.path.join(directory, "main_workflow.py")
            os.remove(main_path)

        ## TODO: extension to other triggers than HTTP
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

        if is_workflow:
            bindings = {
                "main": main_bindings,
                "run_workflow": orchestrator_bindings,
                "run_subworkflow": orchestrator_bindings,
            }
        else:
            bindings = {"function": main_bindings}

        if is_workflow:
            func_dirs = []
            for file_path in glob.glob(os.path.join(directory, file_type)):
                file = os.path.basename(file_path)
                print("file: ", file)

                if file in package_config or file in wrapper_files:
                    continue

                # move file directory/f.py to directory/f/f.py
                name, ext = os.path.splitext(file)
                func_dir = os.path.join(directory, name)
                func_dirs.append(func_dir)

                dst_file = os.path.join(func_dir, file)
                src_file = os.path.join(directory, file)
                os.makedirs(func_dir)
                shutil.move(src_file, dst_file)

                # generate function.json
                script_file = file if (name in bindings and is_workflow) else "handler.py"
                payload = {
                    "bindings": bindings.get(name, activity_bindings),
                    "scriptFile": script_file,
                    "disabled": False,
                }
                dst_json = os.path.join(os.path.dirname(dst_file), "function.json")
                json.dump(payload, open(dst_json, "w"), indent=2)

            # copy every wrapper file to respective function dirs
            for wrapper_file in wrapper_files:
                src_path = os.path.join(directory, wrapper_file)
                for func_dir in func_dirs:
                    dst_path = os.path.join(func_dir, wrapper_file)
                    shutil.copyfile(src_path, dst_path)
                os.remove(src_path)

            for func_dir in func_dirs:
                handler_path = os.path.join(func_dir, WRAPPER_FILES[code_package.language_name][0])
                if self.config.resources.redis_host is not None:
                    replace_string_in_file(
                        handler_path, "{{REDIS_HOST}}", f'"{self.config.resources.redis_host}"'
                    )
                if self.config.resources.redis_password is not None:
                    replace_string_in_file(
                        handler_path,
                        "{{REDIS_PASSWORD}}",
                        f'"{self.config.resources.redis_password}"',
                    )
            run_workflow_path = os.path.join(
                os.path.join(directory, "run_workflow", "run_workflow.py")
            )
            if self.config.resources.redis_host is not None:
                replace_string_in_file(
                    run_workflow_path, "{{REDIS_HOST}}", f'"{self.config.resources.redis_host}"'
                )
            if self.config.resources.redis_password is not None:
                replace_string_in_file(
                    run_workflow_path,
                    "{{REDIS_PASSWORD}}",
                    f'"{self.config.resources.redis_password}"',
                )

        else:
            # generate function.json
            script_file = os.path.join("handler.py")
            payload = {
                "bindings": bindings["function"],
                "scriptFile": script_file,
                "disabled": False,
            }
            dst_json = os.path.join(directory, "function", "function.json")
            # dst_json = os.path.join(directory, "function.json")
            json.dump(payload, open(dst_json, "w"), indent=2)

        # generate host.json
        host_json = {
            "version": "2.0",
            "extensionBundle": {
                "id": "Microsoft.Azure.Functions.ExtensionBundle",
                "version": "[2.*, 3.0.0)",
            },
            # "extensions": {
            #    "durableTask": {
            #        "maxConcurrentActivityFunctions": 1,
            #    }
            # }
        }
        json.dump(host_json, open(os.path.join(directory, "host.json"), "w"), indent=2)

        code_size = Benchmark.directory_size(directory)
        execute(
            "zip -qu -r9 {}.zip * .".format(code_package.benchmark),
            shell=True,
            cwd=directory,
        )
        return directory, code_size

    def publish_function(
        self,
        function: CloudBenchmark,
        code_package: Benchmark,
        container_dest: str,
        repeat_on_failure: bool = False,
    ) -> str:
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

                    storage_account = self.config.resources.data_storage_account(self.cli_instance)
                    resource_group = self.config.resources.resource_group(self.cli_instance)
                    ret = self.cli_instance.execute(
                        "az functionapp function show --function-name function "
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
                print(error)
                # app not found
                if "find app with name" in error and repeat_on_failure:
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

    """
        Publish function code on Azure.
        Boolean flag enables repeating publish operation until it succeeds.
        Useful for publish immediately after function creation where it might
        take from 30-60 seconds for all Azure caches to be updated.

        :param name: function name
        :param repeat_on_failure: keep repeating if command fails on unknown name.
        :return: URL to reach HTTP-triggered function
    """

    def update_benchmark(self, function: CloudBenchmark, code_package: Benchmark):

        # Mount code package in Docker instance
        container_dest = self._mount_function_code(code_package)
        url = self.publish_function(function, code_package, container_dest, True)

        storage_account = self.config.resources.data_storage_account(self.cli_instance)
        resource_group = self.config.resources.resource_group(self.cli_instance)

        self.cli_instance.execute(
            f"az functionapp config appsettings set --name {function.name} "
            f" --resource-group {resource_group} "
            f" --settings STORAGE_CONNECTION_STRING={storage_account.connection_string}"
        )

        trigger = HTTPTrigger(url, self.config.resources.data_storage_account(self.cli_instance))
        trigger.logging_handlers = self.logging_handlers
        function.add_trigger(trigger)

    def update_function_configuration(self, function: Function, code_package: Benchmark):
        # FIXME: this does nothing currently - we don't specify timeout
        self.logging.warning(
            "Updating function's memory and timeout configuration is not supported."
        )

    def _mount_function_code(self, code_package: Benchmark) -> str:
        dest = os.path.join("/mnt", "function", uuid.uuid4().hex)
        self.cli_instance.upload_package(code_package.code_location, dest)
        return dest

    def default_function_name(self, code_package: Benchmark) -> str:
        """
        Functionapp names must be globally unique in Azure.
        """
        func_name = (
            "{}-{}-{}-{}".format(
                code_package.benchmark,
                code_package.language_name,
                code_package.language_version,
                self.config.resources.resources_id,
            )
            .replace(".", "-")
            .replace("_", "-")
        )
        return func_name

    from sebs import azure

    B = TypeVar("B", bound=azure.function.Function)

    def create_benchmark(
        self, code_package: Benchmark, func_name: str, benchmark_cls: Type[B]
    ) -> B:
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
                            " az functionapp create --functions-version 3 "
                            " --resource-group {resource_group} --os-type Linux"
                            " --consumption-plan-location {region} "
                            " --runtime {runtime} --runtime-version {runtime_version} "
                            " --name {func_name} --storage-account {storage_account}"
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
        function = benchmark_cls(
            name=func_name,
            benchmark=code_package.benchmark,
            code_hash=code_package.hash,
            function_storage=function_storage_account,
            cfg=function_cfg,
        )

        # update existing function app
        self.update_benchmark(function, code_package)

        self.cache_client.add_benchmark(
            deployment_name=self.name(),
            language_name=language,
            code_package=code_package,
            benchmark=function,
        )
        return function

    def cached_benchmark(self, function: CloudBenchmark):

        data_storage_account = self.config.resources.data_storage_account(self.cli_instance)
        for trigger in function.triggers_all():
            azure_trigger = cast(AzureTrigger, trigger)
            azure_trigger.logging_handlers = self.logging_handlers
            azure_trigger.data_storage_account = data_storage_account

    def create_function(self, code_package: Benchmark, func_name: str) -> AzureFunction:
        return self.create_benchmark(code_package, func_name, AzureFunction)

    def update_function(self, function: Function, code_package: Benchmark):
        self.update_benchmark(function, code_package)

    def create_workflow(self, code_package: Benchmark, workflow_name: str) -> AzureWorkflow:
        return self.create_benchmark(code_package, workflow_name, AzureWorkflow)

    def update_workflow(self, workflow: Workflow, code_package: Benchmark):
        self.update_benchmark(workflow, code_package)

    """
        Prepare Azure resources to store experiment results.
        Allocate one container.

        :param benchmark: benchmark name
        :return: name of bucket to store experiment results
    """

    def prepare_experiment(self, benchmark: str):
        logs_container = self.storage.add_output_bucket(benchmark, suffix="logs")
        return logs_container

    def download_metrics(
        self,
        function_name: str,
        start_time: int,
        end_time: int,
        requests: Dict[str, ExecutionResult],
        metrics: Dict[str, dict],
    ):

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

        fname = function.name
        resource_group = self.config.resources.resource_group(self.cli_instance)

        self.cli_instance.execute(
            f"az functionapp config appsettings set --name {fname} "
            f" --resource-group {resource_group} "
            f" --settings ForceColdStart={self.cold_start_counter}"
        )

        self.update_function(function, code_package)

    def enforce_cold_start(self, functions: List[Function], code_package: Benchmark):
        self.cold_start_counter += 1
        for func in functions:
            self._enforce_cold_start(func, code_package)
        import time

        time.sleep(20)

    """
        The only implemented trigger at the moment is HTTPTrigger.
        It is automatically created for each function.
    """

    def create_function_trigger(
        self, function: Function, trigger_type: Trigger.TriggerType
    ) -> Trigger:
        raise NotImplementedError()

    def create_workflow_trigger(
        self, workflow: Workflow, trigger_type: Trigger.TriggerType
    ) -> Trigger:
        raise NotImplementedError()
