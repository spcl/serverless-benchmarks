import datetime
import glob
import json
import logging
import os
import shutil
import time
import uuid
from typing import Optional

import docker
import requests

from sebs.azure.blob_storage import BlobStorage
from sebs.azure.config import AzureConfig
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
    docker_instance: Optional[docker.Container]

    # runtime mapping
    AZURE_RUNTIMES = {"python": "python", "nodejs": "node"}

    @staticmethod
    def name():
        return "azure"

    @property
    def config(self) -> AzureConfig:
        return self._config

    def __init__(
        self,
        sebs_config: SeBSConfig,
        config: AWSConfig,
        cache_client: Cache,
        docker_client: docker.client,
    ):
        super().__init__(sebs_config, cache_client, docker_client)
        self._config = config

    """
        Start the Docker container running Azure CLI tools.
        Login 
    """

    def initialize(self, config: Dict[str, str] = {}):
        self.start()
        self.login()

    """
        Shutdowns Dock
    """

    def shutdown(self):
        if self.docker_instance:
            logging.info("Stopping Azure manage Docker instance")
            self.docker_instance.stop()
            self.logged_in = False
            self.docker_instance = None

    """
        Starts an Azure CLI instance in a seperate Docker container.
        The container is used to upload function code, thus it might
        be restarted with a new set of volumes to be mounted.
        TODO: wouldn't it be simpler to just use put_archive method to upload
        function code on-the-fly?
    """

    def start(self, code_package=None, restart=False):
        volumes = {}
        if code_package:
            volumes = {code_package: {"bind": "/mnt/function/", "mode": "rw"}}
        if self.docker_instance and restart:
            self.shutdown()
        if not self.docker_instance or restart:
            # Run Azure CLI docker instance in background
            self.docker_instance = self.docker_client.containers.run(
                image="{}:manage.azure".format(self.system_config.docker_repository()),
                command="/bin/bash",
                user="1000:1000",
                volumes=volumes,
                remove=True,
                stdout=True,
                stderr=True,
                detach=True,
                tty=True,
            )
            logging.info("Starting Azure manage Docker instance")

    """
        Execute the given command in Azure CLI.
        Throws an exception on failure (commands are expected to execute succesfully).
    """

    def execute(self, cmd: str):
        exit_code, out = self.docker_instance.exec_run(cmd)
        if exit_code != 0:
            raise RuntimeError(
                "Command {} failed at Azure CLI docker!\n Output {}".format(
                    cmd, out.decode("utf-8")
                )
            )
        return out

    """
        Run azure login command on Docker instance.
    """

    def login(self):
        self.execute(
            "az login -u {0} --service-principal --tenant {1} -p {2}".format(
                self.config.credentials.appId,
                self.config.credentials.tenant,
                self.config.credentials.password,
            )
        )
        logging.info("Azure login succesful")

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
                self.storage_connection_string,
                replace_existing=replace_existing,
            )
        else:
            self.storage.replace_existing = replace_existing
        return self.storage
        # ensure we have a storage account
        self.storage_account()
        self.storage = blob_storage(replace_existing)
        if benchmark and buckets:
            self.storage.create_buckets(
                benchmark,
                buckets,
                self.cache_client.get_storage_config("azure", benchmark),
            )
        return self.storage

    """
        Locate resource group name in config.
        If not found, then create a new resource group with uuid-based name.

        Requires Azure CLI instance in Docker.
    """

    def resource_group(self):
        # if known, then skip
        if self.resource_group_name:
            return

        # Resource group provided, verify existence
        if "resource_group" in self.config:
            self.resource_group_name = self.config["resource_group"]
            ret = self.execute(
                "az group exists --name {0}".format(self.resource_group_name)
            )
            if ret.decode("utf-8").strip() != "true":
                raise RuntimeError(
                    "Resource group {} does not exists!".format(
                        self.resource_group_name
                    )
                )
        # Create resource group
        else:
            region = self.config["region"]
            uuid_name = str(uuid.uuid1())[0:8]
            # Only underscore and alphanumeric characters are allowed
            self.resource_group_name = "sebs_resource_group_{}".format(uuid_name)
            self.execute(
                "az group create --name {0} --location {1}".format(
                    self.resource_group_name, region
                )
            )
            self.cache_client.update_config(
                val=self.resource_group_name, keys=["azure", "resource_group"]
            )
            logging.info("Resource group {} created.".format(self.resource_group_name))
        logging.info(
            "Azure resource group {} selected".format(self.resource_group_name)
        )
        return self.resource_group_name

    """
        Locate storage account connection string in config.
        If not found, then query the string in Azure using current storage account.

        Requires Azure CLI instance in Docker.
    """

    def query_storage_connection_string(self):
        # if known, then skip
        if self.storage_connection_string:
            return

        if "connection_string" not in self.config["storage"]:
            # Get storage connection string
            ret = self.execute(
                "az storage account show-connection-string --name {}".format(
                    self.storage_account_name
                )
            )
            ret = json.loads(ret.decode("utf-8"))
            self.storage_connection_string = ret["connectionString"]
            self.cache_client.update_config(
                val=self.storage_connection_string,
                keys=["azure", "storage", "connection_string"],
            )
            logging.info(
                "Storage connection string {}.".format(self.storage_connection_string)
            )
        else:
            self.storage_connection_string = self.config["storage"]["connection_string"]
        return self.storage_connection_string

    """
        Locate storage account name and connection string in config.
        If not found, then create a new storage account with uuid-based name.

        Requires Azure CLI instance in Docker.
    """

    def storage_account(self):

        # if known, then skip
        if self.storage_account_name:
            return

        # Storage acount known, only verify correctness
        if "storage" in self.config:
            self.storage_account_name = self.config["storage"]["account"]
            try:
                # There's no API to check existence.
                # Thus, we attempt to query basic info and check for failures.
                ret = self.execute(
                    "az storage account show --name {0}".format(
                        self.storage_account_name
                    )
                )
            except RuntimeError as e:
                raise RuntimeError(
                    "Storage account {} existence verification failed!".format(
                        self.storage_account_name
                    )
                )
        # Create storage account
        else:
            region = self.config["region"]
            # Ensure we have resource group
            self.resource_group()
            sku = "Standard_LRS"
            # Create account. Only alphanumeric characters are allowed
            uuid_name = str(uuid.uuid1())[0:8]
            self.storage_account_name = "sebsstorage{}".format(uuid_name)
            self.execute(
                (
                    "az storage account create --name {0} --location {1} "
                    "--resource-group {2} --sku {3}"
                ).format(
                    self.storage_account_name, region, self.resource_group_name, sku
                )
            )
            self.cache_client.update_config(
                val=self.storage_account_name, keys=["azure", "storage", "account"]
            )
            logging.info(
                "Storage account {} created.".format(self.storage_account_name)
            )
        self.query_storage_connection_string()
        logging.info(
            "Azure storage account {} selected".format(self.storage_account_name)
        )
        return self.storage_account_name

    # TODO: currently we rely on Azure remote build
    # Thus we only rearrange files
    # Directory structure
    # handler
    # - source files
    # - Azure wrappers - handler, storage
    # - additional resources
    # - function.json
    # host.json
    # requirements.txt/package.json
    def package_code(self, dir, benchmark):

        # In previous step we ran a Docker container which installed packages
        # Python packages are in .python_packages because this is expected by Azure
        EXEC_FILES = {"python": "handler.py", "nodejs": "handler.js"}
        CONFIG_FILES = {
            "python": ["requirements.txt", ".python_packages"],
            "nodejs": ["package.json", "node_modules"],
        }
        package_config = CONFIG_FILES[self.language]

        handler_dir = os.path.join(dir, "handler")
        os.makedirs(handler_dir)
        # move all files to 'handler' except package config
        for file in os.listdir(dir):
            if file not in package_config:
                file = os.path.join(dir, file)
                shutil.move(file, handler_dir)

        # generate function.json
        # TODO: extension to other triggers than HTTP
        default_function_json = {
            "scriptFile": EXEC_FILES[self.language],
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
        json_out = os.path.join(dir, "handler", "function.json")
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
            default_host_json, open(os.path.join(dir, "host.json"), "w"), indent=2
        )

        # copy handlers
        wrappers_dir = project_absolute_path("cloud-frontend", "azure", self.language)
        for file in glob.glob(os.path.join(wrappers_dir, "*.py")):
            shutil.copy(os.path.join(wrappers_dir, file), handler_dir)

        return dir

    """
        Publish function code on Azure.
        Boolean flag enables repeating publish operation until it succeeds.
        Useful for publish immediately after function creation where it might
        take from 30-60 seconds for all Azure caches to be updated.

        :param name: function name
        :param repeat_on_failure: keep repeating if command fails on unknown name.
        :return: URL to reach HTTP-triggered function
    """

    def publish_function(self, name: str, repeat_on_failure: bool = False):

        success = False
        url = ""
        while not success:
            try:
                ret = self.execute(
                    "bash -c 'cd /mnt/function "
                    "&& func azure functionapp publish {} --{} --no-build'".format(
                        name, self.AZURE_RUNTIMES[self.language]
                    )
                )
                print(ret)
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
                            name
                        )
                    )
                # escape loop. we failed!
                else:
                    raise e
        return url

    """
        a)  if a cached function is present and no update flag is passed,
            then just return function name
        b)  if a cached function is present and update flag is passed,
            then upload new code
        c)  if no cached function is present, then create code package and
            either create new function on AWS or update an existing one

        :param benchmark:
        :param benchmark_path: Path to benchmark code
        :param config: JSON config for benchmark
        :param function_name: Override randomly generated function name
        :return: function name, code size
    """

    def create_function(self, code_package: CodePackage, experiment_config: dict):

        benchmark = code_package.benchmark
        if code_package.is_cached and code_package.is_cached_valid:
            func_name = code_package.cached_config["name"]
            self.url = code_package.cached_config["invoke_url"]
            code_location = code_package.code_location
            logging.info(
                "Using cached function {fname} in {loc}".format(
                    fname=func_name, loc=code_location
                )
            )
            return func_name
        # b) cached_instance, create package and update code
        elif code_package.is_cached:

            func_name = code_package.cached_config["name"]
            code_location = code_package.code_location
            timeout = code_package.benchmark_config["timeout"]
            memory = code_package.benchmark_config["memory"]

            # Run Azure-specific part of building code.
            package = self.package_code(code_location, code_package.benchmark)
            code_size = CodePackage.directory_size(code_location)
            # Restart Docker instance to make sure code package is mounted
            self.start(package, restart=True)
            # Publish function
            url = self.publish_function(func_name)
            self.url = url

            cached_cfg = code_package.cached_config
            cached_cfg["code_size"] = code_size
            cached_cfg["hash"] = code_package.hash
            cached_cfg["invoke_url"] = url
            self.cache_client.update_function(
                "azure", benchmark, self.language, package, cached_cfg
            )

            logging.info(
                "Updating cached function {fname} in {loc}".format(
                    fname=func_name, loc=code_location
                )
            )

            return func_name
        # c) no cached instance, create package and upload code
        else:

            code_location = code_package.code_location
            timeout = code_package.benchmark_config["timeout"]
            memory = code_package.benchmark_config["memory"]

            # Restart Docker instance to make sure code package is mounted
            self.start(code_location, restart=True)
            self.storage_account()
            self.resource_group()

            # create function name
            region = self.config["config"]["region"]
            # only hyphens are allowed
            # and name needs to be globally unique
            uuid_name = str(uuid.uuid1())[0:8]
            func_name = (
                "{}-{}-{}".format(benchmark, self.language, uuid_name)
                .replace(".", "-")
                .replace("_", "-")
            )

            # check if function does not exist
            # no API to verify existence
            try:
                self.execute(
                    ("az functionapp show --resource-group {} " "--name {}").format(
                        self.resource_group_name, func_name
                    )
                )
            except:
                # create function app
                ret = self.execute(
                    (
                        "az functionapp create --resource-group {} "
                        "--os-type Linux --consumption-plan-location {} "
                        "--runtime {} --runtime-version {} --name {} "
                        "--storage-account {}"
                    ).format(
                        self.resource_group_name,
                        region,
                        self.AZURE_RUNTIMES[self.language],
                        self.config["config"]["runtime"][self.language],
                        func_name,
                        self.storage_account_name,
                    )
                )
                logging.info("Created function app {}".format(func_name))

            logging.info("Selected {} function app".format(func_name))
            # Run Azure-specific part of building code.
            package = self.package_code(code_location, code_package.benchmark)
            code_size = CodePackage.directory_size(code_location)
            # Restart Docker instance to make sure code package is mounted
            self.start(package, restart=True)
            # update existing function app
            url = self.publish_function(func_name, repeat_on_failure=True)
            self.url = url

            self.cache_client.add_function(
                deployment="azure",
                benchmark=benchmark,
                language=self.language,
                code_package=package,
                language_config={
                    "invoke_url": url,
                    "runtime": self.config["config"]["runtime"][self.language],
                    "name": func_name,
                    "code_size": code_size,
                    "resource_group": self.resource_group_name,
                    "hash": code_package.hash,
                },
                storage_config={
                    "account": self.storage_account_name,
                    "containers": {
                        "input": self.storage.input_containers,
                        "output": self.storage.output_containers,
                    },
                },
            )
        return func_name, code_size

    """
        Prepare Azure resources to store experiment results.
        Allocate one container.

        :param benchmark: benchmark name
        :return: name of bucket to store experiment results
    """

    def prepare_experiment(self, benchmark: str):
        logs_container = self.storage.add_output_container(benchmark, suffix="logs")
        return logs_container

    def invoke_sync(self, name: str, payload: dict):

        payload["connection_string"] = self.storage_connection_string
        begin = datetime.datetime.now()
        ret = requests.request(method="POST", url=self.url, json=payload)
        end = datetime.datetime.now()

        if ret.status_code != 200:
            logging.error("Invocation of {} failed!".format(name))
            logging.error("Input: {}".format(payload))
            raise RuntimeError()

        ret = ret.json()
        vals = {}
        vals["return"] = ret
        vals["client_time"] = (end - begin) / datetime.timedelta(microseconds=1)
        return vals

    def download_metrics(
        self,
        function_name: str,
        deployment_config: dict,
        start_time: int,
        end_time: int,
        requests: dict,
    ):
        self.login()

        resource_group = deployment_config["resource_group"]
        app_id_query = self.execute(
            (
                "az monitor app-insights component show " "--app {} --resource-group {}"
            ).format(function_name, resource_group)
        ).decode("utf-8")
        application_id = json.loads(app_id_query)["appId"]

        # Azure CLI requires date in the following format
        # Format: date (yyyy-mm-dd) time (hh:mm:ss.xxxxx) timezone (+/-hh:mm)
        # Include microseconds time to make sure we're not affected by
        # miliseconds precision.
        start_time = datetime.datetime.fromtimestamp(start_time).strftime(
            "%Y-%m-%d %H:%M:%S.%f"
        )
        end_time = datetime.datetime.fromtimestamp(end_time).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        import pytz
        from pytz import reference

        tz = reference.LocalTimezone().tzname(datetime.datetime.now())
        timezone_str = datetime.datetime.now(pytz.timezone(tz)).strftime("%z")

        query = (
            "requests | project timestamp, operation_Name, success, "
            "resultCode, duration, cloud_RoleName, "
            "invocationId=customDimensions['InvocationId'], "
            "functionTime=customDimensions['FunctionExecutionTimeMs']"
        )
        ret = self.execute(
            (
                'az monitor app-insights query --app {} --analytics-query "{}" '
                "--start-time {} {} --end-time {} {}"
            ).format(
                application_id, query, start_time, timezone_str, end_time, timezone_str
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

    def create_azure_function(self, fname, config):

        # create function name
        region = self.config["config"]["region"]
        # only hyphens are allowed
        # and name needs to be globally unique
        uuid_name = str(uuid.uuid1())[0:8]
        func_name = fname.replace(".", "-").replace("_", "-")

        # create function app
        ret = self.execute(
            (
                "az functionapp create --resource-group {} "
                "--os-type Linux --consumption-plan-location {} "
                "--runtime {} --runtime-version {} --name {} "
                "--storage-account {}"
            ).format(
                self.resource_group_name,
                region,
                self.AZURE_RUNTIMES[self.language],
                self.config["config"]["runtime"][self.language],
                func_name,
                self.storage_account_name,
            )
        )
        logging.info("Created function app {}".format(func_name))
        return func_name

    init = False

    def create_function_copies(
        self,
        function_names: List[str],
        code_package: CodePackage,
        experiment_config: dict,
    ):

        if not self.init:
            code_location = code_package.code_location
            # package = self.package_code(code_location, code_package.benchmark)
            code_size = code_package.code_size
            # Restart Docker instance to make sure code package is mounted
            self.start(code_location, restart=True)
            self.storage_account()
            self.resource_group()
            self.login()
            self.init = True

        # names = []
        # for fname in function_names:
        #    names.append(self.create_azure_function(fname, experiment_config))
        names = function_names

        # time.sleep(30)
        urls = []
        for fname in function_names:
            url = self.publish_function(fname, repeat_on_failure=True)
            urls.append(url)
            logging.info("Published function app {} with URL {}".format(fname, url))

        return names, urls
