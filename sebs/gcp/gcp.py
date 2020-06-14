
from typing import Dict, Tuple

import docker
from googleapiclient.discovery import build
import os
import datetime
import time
import logging
import shutil
import sebs.benchmark
from sebs.cache import Cache
from sebs.config import SeBSConfig
from scripts.experiments_utils import *
from CodePackage import CodePackage
import json
from sebs.utils import execute
from .function import Function
from .storage import PersistentStorage
from ..faas.system import System
from sebs.gcp.config import GCPConfig
from sebs.gcp.storage import GCPStorage

"""
    This class provides basic abstractions for the FaaS system.
    It provides the interface for initialization of the system and storage
    services, creation and update of serverless functions and querying
    logging and measurements services to obtain error messages and performance
    measurements.
"""


class GCP(System):

    storage: GCPStorage
    _config: GCPConfig

    def __init__(
        self,
        system_config: SeBSConfig,
        config: GCPConfig,
        cache_client: Cache,
        docker_client: docker.client,
    ):
        # self._system_config = system_config
        # self._docker_client = docker_client
        # self._cache_client = cache_client

        super().__init__(system_config, cache_client, docker_client)
        self._config = config


    @property
    def system_config(self) -> SeBSConfig:
        return self._system_config

    @property
    def docker_client(self) -> docker.client:
        return self._docker_client

    @property
    def cache_client(self) -> Cache:
        return self._cache_client

    @property
    def config(self) -> GCPConfig:
        return self._config

    """
        Initialize the system. After the call the local or remot
        FaaS system should be ready to allocate functions, manage
        storage resources and invoke functions.

        :param config: systems-specific parameters
    """

    def initialize(self, config: Dict[str, str] = {}):
        self.function_client = build("cloudfunctions", "v1")
        self.get_storage()

    """
        Access persistent storage instance.
        It might be a remote and truly persistent service (AWS S3, Azure Blob..),
        or a dynamically allocated local instance.

        :param replace_existing: replace benchmark input data if exists already
    """

    def get_storage(self, replace_existing: bool, benchmark=None, buckets=None,) -> PersistentStorage:
        self.storage = GCPStorage(replace_existing)
        if benchmark and buckets:
            self.storage.allocate_buckets(benchmark, buckets, self.cache_client.get_storage_config('gcp', benchmark))
        return self.storage

    """
        Apply the system-specific code packaging routine to build benchmark.
        The benchmark creates a code directory with the following structure:
        - [benchmark sources]
        - [benchmark resources]
        - [dependence specification], e.g. requirements.txt or package.json
        - [handlers implementation for the language and deployment]

        This step allows us to change the structure above to fit different
        deployment requirements, Example: a zip file for AWS or a specific
        directory structure for Azure.

        :return: path to packaged code and its size
    """

    def package_code(self, benchmark: sebs.benchmark.Benchmark, dir) -> Tuple[str, int]:
        CONFIG_FILES = {
            'python': ['handler.py', 'requirements.txt', '.python_packages'],
            'nodejs': ['handler.js', 'node_modules']
        }
        HANDLER = {
            'python': ('handler.py', 'main.py'),
            'nodejs': ('handler.js', 'index.js')
        }
        package_config = CONFIG_FILES[self.language]
        function_dir = os.path.join(dir, 'function')
        os.makedirs(function_dir)
        for file in os.listdir(dir):
            if file not in package_config:
                file = os.path.join(dir, file)
                shutil.move(file, function_dir)

        cur_dir = os.getcwd()
        os.chdir(dir)
        old_name, new_name = HANDLER[self.language]
        shutil.move(old_name, new_name)

        execute("zip -qu -r9 {}.zip * .".format(benchmark), shell=True)
        benchmark_archive = "{}.zip".format(os.path.join(dir, benchmark))
        logging.info('Created {} archive'.format(benchmark_archive))

        shutil.move(new_name, old_name)
        os.chdir(cur_dir)
        return os.path.join(dir, "{}.zip".format(benchmark))

    """
        a)  if a cached function is present and no update flag is passed,
            then just return function name
        b)  if a cached function is present and update flag is passed,
            then upload new code
        c)  if no cached function is present, then create code package and
            either create new function on AWS or update an existing one

        :param benchmark:
        :param config: JSON config for benchmark
        :param function_name: Override randomly generated function name
        :return: function name, code size
    """

    def get_function(self, code_package: sebs.benchmark.Benchmark) -> Function:
        benchmark = code_package.benchmark
        self.location = self.config["experiments"]["deployment"]["config"]["region"]
        self.project_name = self.config["experiments"]["deployment"]["config"]["project_name"]
        project_name = self.project_name
        location = self.location

        if code_package.is_cached and code_package.is_cached_valid:
            func_name = code_package.cached_config["name"]
            code_location = code_package.code_location
            logging.info('Using cached function {fname} in {loc}'.format(
                fname=func_name,
                loc=code_location
            ))
            return func_name

        elif code_package.is_cached:
            func_name = code_package.cached_config["name"]
            full_func_name = "projects/{project_name}/locations/{location}/functions/{func_name}".format(
                project_name=project_name, location=location, func_name=func_name)
            code_location = code_package.code_location
            timeout = code_package.benchmark_config["timeout"]
            memory = code_package.benchmark_config["memory"]

            package = self.package_code(code_location, code_package.benchmark)
            code_package_name = os.path.basename(package)
            self.update_function(benchmark, full_func_name, code_package_name, code_package, timeout, memory)
            code_size = CodePackage.directory_size(code_location)

            cached_cfg = code_package.cached_config
            cached_cfg["code_size"] = code_size
            cached_cfg["timeout"] = timeout
            cached_cfg["memory"] = memory
            cached_cfg["hash"] = code_package.hash
            self.cache_client.update_function('gcp', benchmark, self.language, package, cached_cfg)

            logging.info("Updating cached function {fname} in {loc}".format(
                fname=func_name,
                loc=code_location
            ))

            return func_name
        else:
            code_location = code_package.code_location
            timeout = code_package.benchmark_config["timeout"]
            memory = code_package.benchmark_config["memory"]
            code_size = CodePackage.directory_size(code_location)

            func_name = 'foo_{}-{}-{}'.format(benchmark, self.language, memory)
            func_name = func_name.replace('-', '_')
            func_name = func_name.replace('.', '_')

            package = self.package_code(code_location, code_package.benchmark)

            code_package_name = os.path.basename(package)
            bucket, idx = self.storage.add_input_bucket(benchmark)
            self.storage.upload(bucket, code_package_name, package)
            logging.info('Uploading function {} code to {}'.format(func_name, bucket))
            blob = self.storage.client.bucket(bucket).blob(code_package_name)
            # signed_url = blob.generate_signed_url(
            #     version="v4",
            #     expiration=datetime.timedelta(minutes=15),
            #     method="GET",  # TODO I'm not sure which method to put here
            # )

            print("config: ", self.config)
            req = self.function_client.projects().locations().functions().list(
                parent="projects/{project_name}/locations/{location}"
                    .format(project_name=project_name, location=location))
            res = req.execute()

            full_func_name = "projects/{project_name}/locations/{location}/functions/{func_name}".format(
                project_name=project_name, location=location, func_name=func_name)
            if "functions" in res.keys() and full_func_name in [f["name"] for f in res["functions"]]:
                self.update_function(benchmark, full_func_name, code_package_name, code_package, timeout, memory)
            else:
                language_runtime = str(self.config['config']['runtime'][self.language])
                print("language runtime: ", self.language + language_runtime.replace(".", ""))
                req = self.function_client.projects().locations().functions().create(
                    location="projects/{project_name}/locations/{location}".format(project_name=project_name,
                                                                                   location=location),
                    body={
                        "name": full_func_name,
                        "entryPoint": "handler",
                        "runtime": self.language + language_runtime.replace(".", ""),
                        "availableMemoryMb": memory,
                        "timeout": str(timeout) + "s",
                        "httpsTrigger": {},
                        "sourceArchiveUrl": "gs://" + bucket + "/" + code_package_name,
                    }
                )
                print("request: ", req)
                res = req.execute()
                print("response:", res)

            our_function_req = self.function_client.projects().locations().functions().get(name=full_func_name)
            res = our_function_req.execute()
            invoke_url = res["httpsTrigger"]["url"]
            print("RESPONSE: ", res)

            self.cache_client.add_function(
                deployment="gcp",
                benchmark=benchmark,
                language=self.language,
                code_package=package,
                language_config={
                    "name": func_name,
                    "code_size": code_size,
                    "runtime": self.config['config']['runtime'][self.language],
                    'memory': memory,
                    'timeout': timeout,
                    'hash': code_package.hash,
                    'url': invoke_url
                },
                storage_config={
                    "buckets": {
                        "input": self.storage.input_buckets,
                        "output": self.storage.output_buckets
                    }
                }
            )
            return func_name

    # FIXME: trigger allocation API
    # FIXME: result query API
    # FIXME: metrics query API
    def update_function(self, benchmark, full_func_name, code_package_name, code_package, timeout, memory):
        language_runtime = str(self.config['config']['runtime'][self.language])
        bucket, idx = self.storage.add_input_bucket(benchmark)
        req = self.function_client.projects().locations().functions().patch(
            name=full_func_name,
            body={
                "name": full_func_name,
                "entryPoint": "handler",
                "runtime": self.language + language_runtime.replace(".", ""),
                "availableMemoryMb": memory,
                "timeout": str(timeout) + "s",
                "httpsTrigger": {},
                "sourceArchiveUrl": "gs://" + bucket + "/" + code_package_name,
            })
        res = req.execute()
        print("response:", res)
        logging.info('Updating GCP code of function {} from {}'.format(full_func_name, code_package))

    def prepare_experiment(self, benchmark):
        logs_bucket = self.storage.add_output_bucket(benchmark, suffix='logs')
        return logs_bucket


    def prepare_experiment(self, benchmark):
        logs_bucket = self.storage.add_output_bucket(benchmark, suffix='logs')
        return logs_bucket

    def invoke_sync(self, name: str, payload: dict):
        full_func_name = "projects/{project_name}/locations/{location}/functions/{func_name}".format(
            project_name=self.project_name, location=self.location, func_name=name)
        print(payload)
        payload = json.dumps(payload)
        print(payload)

        status_req = self.function_client.projects().locations().functions().get(name=full_func_name)
        deployed = False
        while not deployed:
            status_res = status_req.execute()
            if status_res['status'] == 'ACTIVE':
                deployed = True
            else:
                time.sleep(5)

        req = self.function_client.projects().locations().functions().call(
            name=full_func_name,
            body={
                "data": payload
            }
        )
        begin = datetime.datetime.now()
        res = req.execute()
        end = datetime.datetime.now()

        print("RES: ", res)

        if "error" in res.keys() and res["error"] != "":
            logging.error('Invocation of {} failed!'.format(name))
            logging.error('Input: {}'.format(payload))
            raise RuntimeError()

        print("Result", res["result"])
        return {"return": res["result"], "client_time": (end - begin) / datetime.timedelta(microseconds=1)}

    def invoke_async(self, name: str, payload: dict):
        print("Nope")

    def shutdown(self):
        pass

    def download_metrics(self, function_name: str, deployment_config: dict,
                         start_time: int, end_time: int, requests: dict):
        pass

    def create_function_copies(self, function_names: List[str], api_name: str, memory: int, timeout: int,
                               code_package: CodePackage, experiment_config: dict, api_id: str = None):
        pass





    # @abstractmethod
    # def get_invocation_error(self, function_name: str,
    #   start_time: int, end_time: int):
    #    pass

    # @abstractmethod
    # def download_metrics(self):
    #    pass

    @staticmethod
    def name() -> str:
        return "gcp"
