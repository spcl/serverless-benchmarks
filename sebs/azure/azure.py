import datetime
import json
import logging
import os
import shutil
import time
from typing import cast, Dict, List, Optional, Tuple, Type # noqa

import docker

from sebs.azure.blob_storage import BlobStorage
from sebs.azure.cli import AzureCLI
from sebs.azure.function import AzureFunction
from sebs.azure.config import AzureConfig
from sebs.azure.triggers import AzureTrigger, HTTPTrigger
from sebs.benchmark import Benchmark
from sebs.cache import Cache
from sebs.config import SeBSConfig
from ..faas.function import Function, ExecutionResult
from ..faas.storage import PersistentStorage
from ..faas.system import System


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

    def __init__(
        self,
        sebs_config: SeBSConfig,
        config: AzureConfig,
        cache_client: Cache,
        docker_client: docker.client,
    ):
        super().__init__(sebs_config, cache_client, docker_client)
        self._config = config

    """
        Start the Docker container running Azure CLI tools.
    """

    def initialize(self, config: Dict[str, str] = {}):
        self.cli_instance = AzureCLI(self.system_config, self.docker_client)
        self.cli_instance.login(
            appId=self.config.credentials.appId,
            tenant=self.config.credentials.tenant,
            password=self.config.credentials.password,
        )

    def shutdown(self):
        if self.cli_instance:
            self.cli_instance.shutdown()
        self.config.update_cache(self.cache_client)

    # """
    #    Starts an Azure CLI instance in a seperate Docker container.
    #    The container is used to upload function code, thus it might
    #    be restarted with a new set of volumes to be mounted.
    #    TODO: wouldn't it be simpler to just use put_archive method to upload
    #    function code on-the-fly?
    # """

    # def start(self, code_package=None, restart=False):
    #    volumes = {}
    #    if code_package:
    #        volumes = {code_package: {"bind": "/mnt/function/", "mode": "rw"}}
    #    if self.docker_instance and restart:
    #        self.shutdown()
    #    if not self.docker_instance or restart:
    #        # Run Azure CLI docker instance in background
    #        self.docker_instance = self.docker_client.containers.run(
    #            image="{}:manage.azure".format(self.system_config.docker_repository()),
    #            command="/bin/bash",
    #            user="1000:1000",
    #            volumes=volumes,
    #            remove=True,
    #            stdout=True,
    #            stderr=True,
    #            detach=True,
    #            tty=True,
    #        )
    #        logging.info("Starting Azure manage Docker instance")

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
                self.cache_client,
                self.config.resources.data_storage_account(
                    self.cli_instance
                ).connection_string,
                replace_existing=replace_existing,
            )
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
        self, directory: str, language_name: str, benchmark: str
    ) -> Tuple[str, int]:

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
                    "authLevel": "function",
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
                "version": "[1.*, 2.0.0)",
            },
        }
        json.dump(
            default_host_json, open(os.path.join(directory, "host.json"), "w"), indent=2
        )

        code_size = Benchmark.directory_size(directory)
        return directory, code_size

    def publish_function(
        self,
        function: Function,
        code_package: Benchmark,
        repeat_on_failure: bool = False,
    ) -> str:
        success = False
        url = ""
        logging.info("Attempting publish of function {}".format(function.name))
        while not success:
            try:
                ret = self.cli_instance.execute(
                    "bash -c 'cd /mnt/function "
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
                if url == "":
                    raise RuntimeError(
                        "Couldnt find URL in {}".format(ret.decode("utf-8"))
                    )
                success = True
            except RuntimeError as e:
                error = str(e)
                # app not found
                if "find app with name" in error and repeat_on_failure:
                    # Sleep because of problems when publishing immediately
                    # after creating function app.
                    time.sleep(30)
                    logging.info(
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

    def update_function(self, function: Function, code_package: Benchmark):

        # Mount code package in Docker instance
        self._mount_function_code(code_package)
        url = self.publish_function(function, code_package, True)

        function.add_trigger(
            HTTPTrigger(
                url, self.config.resources.data_storage_account(self.cli_instance)
            )
        )

    def _mount_function_code(self, code_package: Benchmark):
        self.cli_instance.upload_package(code_package.code_location, "/mnt/function/")

    def default_function_name(self, code_package: Benchmark) -> str:
        """
            Functionapp names must be globally unique in Azure.
        """
        func_name = (
            "{}-{}-{}".format(
                code_package.benchmark, code_package.language_name, self.config.resources_id
            )
            .replace(".", "-")
            .replace("_", "-")
        )
        return func_name

    def create_function(self, code_package: Benchmark, func_name: str) -> AzureFunction:

        language = code_package.language_name
        language_runtime = code_package.language_version
        resource_group = self.config.resources.resource_group(self.cli_instance)
        region = self.config.region

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
            self.cli_instance.execute(
                (
                    " az functionapp show --resource-group {resource_group} "
                    " --name {func_name} "
                ).format(**config)
            )
            # FIXME: get the current storage account
        except RuntimeError:
            function_storage_account = self.config.resources.add_storage_account(
                self.cli_instance
            )
            config["storage_account"] = function_storage_account.account_name
            # FIXME: only Linux type is supported
            # create function app
            self.cli_instance.execute(
                (
                    " az functionapp create --resource-group {resource_group} "
                    " --os-type Linux --consumption-plan-location {region} "
                    " --runtime {runtime} --runtime-version {runtime_version} "
                    " --name {func_name} --storage-account {storage_account}"
                ).format(**config)
            )
            logging.info("Azure: Created function app {}".format(func_name))
            function = AzureFunction(
                name=func_name,
                code_hash=code_package.hash,
                function_storage=function_storage_account,
            )

        logging.info("Azure: Selected {} function app".format(func_name))
        # update existing function app
        self.update_function(function, code_package)

        self.cache_client.add_function(
            deployment_name=self.name(),
            language_name=language,
            code_package=code_package,
            function=function,
        )
        return function

    def cached_function(self, function: Function):

        data_storage_account = self.config.resources.data_storage_account(
            self.cli_instance
        )
        for trigger in function.triggers:
            azure_trigger = cast(AzureTrigger, trigger)
            azure_trigger.data_storage_account = data_storage_account

    """
        Prepare Azure resources to store experiment results.
        Allocate one container.

        :param benchmark: benchmark name
        :return: name of bucket to store experiment results
    """

    def prepare_experiment(self, benchmark: str):
        logs_container = self.storage.add_output_bucket(benchmark, suffix="logs")
        return logs_container

    #    def invoke_sync(self, name: str, payload: dict):
    #
    #        payload["connection_string"] = self.storage_connection_string
    #        begin = datetime.datetime.now()
    #        ret = requests.request(method="POST", url=self.url, json=payload)
    #        end = datetime.datetime.now()
    #
    #        if ret.status_code != 200:
    #            logging.error("Invocation of {} failed!".format(name))
    #            logging.error("Input: {}".format(payload))
    #            raise RuntimeError()
    #
    #        ret = ret.json()
    #        vals = {}
    #        vals["return"] = ret
    #        vals["client_time"] = (end - begin) / datetime.timedelta(microseconds=1)
    #        return vals
    #
    def download_metrics(
        self,
        function_name: str,
        start_time: int,
        end_time: int,
        requests: List[ExecutionResult],
    ):

        resource_group = self.config.resources.resource_group(self.cli_instance)
        app_id_query = self.cli_instance.execute(
            (
                "az monitor app-insights component show " "--app {} --resource-group {}"
            ).format(function_name, resource_group)
        ).decode("utf-8")
        application_id = json.loads(app_id_query)["appId"]

        # Azure CLI requires date in the following format
        # Format: date (yyyy-mm-dd) time (hh:mm:ss.xxxxx) timezone (+/-hh:mm)
        # Include microseconds time to make sure we're not affected by
        # miliseconds precision.
        start_time_str = datetime.datetime.fromtimestamp(start_time).strftime(
            "%Y-%m-%d %H:%M:%S.%f"
        )
        end_time_str = datetime.datetime.fromtimestamp(end_time).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        import pytz

        tz = pytz.reference.LocalTimezone().tzname(datetime.datetime.now())
        timezone_str = datetime.datetime.now(pytz.timezone(tz)).strftime("%z")

        query = (
            "requests | project timestamp, operation_Name, success, "
            "resultCode, duration, cloud_RoleName, "
            "invocationId=customDimensions['InvocationId'], "
            "functionTime=customDimensions['FunctionExecutionTimeMs']"
        )
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
            duration = request[4]
            func_exec_time = request[-1]
            invocation_id = request[-2]
            requests[invocation_id]["azure"] = {
                "duration": duration,
                "func_time": float(func_exec_time),
            }

        # TODO: query performance counters for mem


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
