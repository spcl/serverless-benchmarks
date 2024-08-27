import logging
import os
import re
import shutil
import subprocess
from typing import cast, Dict, List, Optional, Tuple, Type

import docker
import json
from time import sleep
from typing import Dict, Tuple, List
from sebs.faas.storage import PersistentStorage
from sebs.cache import Cache
from sebs.config import SeBSConfig
from sebs.fission.triggers import LibraryTrigger, HTTPTrigger
from sebs.faas.function import Function, Trigger, ExecutionResult
from sebs.faas.system import System
from sebs.utils import DOCKER_DIR, LoggingHandlers, execute
from sebs.benchmark import Benchmark
from sebs.fission.config import FissionConfig
from sebs.fission.storage import Minio
from .function import FissionFunction, FissionFunctionConfig

class Fission(System):
    _config: FissionConfig

    def __init__(
        self,
        system_config: SeBSConfig,
        config: FissionConfig,
        cache_client: Cache,
        docker_client: docker.client,
        logger_handlers: LoggingHandlers,
    ):
        super().__init__(system_config, cache_client, docker_client)
        self._config = config
        self.logging_handlers = logger_handlers

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

    def initialize(self, config: Dict[str, str] = {}, resource_prefix: Optional[str] = None):
        self.initialize_resources(select_prefix=resource_prefix) 

    @property
    def config(self) -> SeBSConfig:
        return self._config

    def get_storage(self, replace_existing: bool = False) -> PersistentStorage:
        if not hasattr(self, "storage"):

            if not self.config.resources.storage_config:
                raise RuntimeError(
                    "Fission is missing the configuration of pre-allocated storage!"
                )
            self.storage = Minio.deserialize(
                self.config.resources.storage_config, self.cache_client, self.config.resources
            )
            self.storage.logging_handlers = self.logging_handlers
        else:
            self.storage.replace_existing = replace_existing
        return self.storage

    def shutdown(self) -> None:
        if hasattr(self, "storage") and self.config.shutdownStorage:
            self.storage.stop()
        if self.config.removeCluster:
            from tools.fission_preparation import delete_cluster  # type: ignore

            delete_cluster()
        super().shutdown()

    @staticmethod
    def name() -> str:
        return "fission"

    @staticmethod
    def typename():
        return "Fission"

    @staticmethod
    def function_type() -> "Type[Function]":
        return FissionFunction 
    
    def get_fission_cmd(self) -> List[str]:
        cmd = [self.config.fission_exec]
        return cmd

    # not sure if if required
    def find_image(self, repository_name, image_tag) -> bool:

        if self.config.experimentalManifest:
            try:
                # This requires enabling experimental Docker features
                # Furthermore, it's not yet supported in the Python library
                execute(f"docker manifest inspect {repository_name}:{image_tag}")
                return True
            except RuntimeError:
                return False
        else:
            try:
                # default version requires pulling for an image
                self.docker_client.images.pull(repository=repository_name, tag=image_tag)
                return True
            except docker.errors.NotFound:
                return False
    
    def build_base_image(
        self,
        directory: str,
        language_name: str,
        language_version: str,
        benchmark: str,
        is_cached: bool,
    ) -> bool:
        # This needs to be implemented when implementing the container deployment
        pass


    def package_code(
        self,
        directory: str,
        language_name: str,
        language_version: str,
        benchmark: str,
        is_cached: bool,
    ) -> Tuple[str, int]:
        
        # Use this when wokring for container deployment supports.
        # self.build_base_image(directory, language_name, language_version, benchmark, is_cached)

        repo_name = self.system_config.docker_repository()

        enviroment_name = language_name + language_version.replace(".","")
        builder_image = self.system_config.benchmark_base_images(self.name(), language_name)[
            language_version
        ]

        runtime_image = "runtime.{deployment}.{language}.{runtime}".format(
        deployment="fission",
        language=language_name,
        runtime=language_version,
        )

        runtime_image = repo_name + ":" + runtime_image 

        storage_args = self.storage_arguments()
        self.config.resources.create_enviroment(name = enviroment_name, image = runtime_image, builder = builder_image, runtime_env = storage_args)


        CONFIG_FILES = {
            "python": ["handler.py", "requirements.txt", ".python_packages"],
            "nodejs": ["handler.js", "package.json", "node_modules"],
        }
        package_config = CONFIG_FILES[language_name]

        function_dir = os.path.join(directory, "function")
        os.makedirs(function_dir)
        for file in os.listdir(directory):
            if file not in package_config:
                file = os.path.join(directory, file)
                shutil.move(file, function_dir)


        # FIXME: use zipfile
        # create zip with hidden directory but without parent directory
        execute("rm requirements.txt", shell=True, cwd=directory)
        execute("zip -qu -r9 {}.zip * .".format(benchmark), shell=True, cwd=directory)
        benchmark_archive = "{}.zip".format(os.path.join(directory, benchmark))
        self.logging.info("Created {} archive".format(benchmark_archive))
        
        bytes_size = os.path.getsize(os.path.join(function_dir, benchmark_archive))
        mbytes = bytes_size / 1024.0 / 1024.0
        self.logging.info("Zip archive size {:2f} MB".format(mbytes))

        package_name = benchmark  + "-" + language_name + "-" + language_version 
        package_name = package_name.replace(".","")
        self.config.resources.create_package(package_name = package_name, path = benchmark_archive, env_name = enviroment_name)

        return benchmark_archive, bytes_size


    def storage_arguments(self) -> List[str]:
        storage = cast(Minio, self.get_storage())
        return [
        f"MINIO_STORAGE_SECRET_KEY={storage.config.secret_key}",
        f"MINIO_STORAGE_ACCESS_KEY={storage.config.access_key}",
        f"MINIO_STORAGE_CONNECTION_URL={storage.config.address}"
        ]


    def create_function(self, code_package: Benchmark, func_name: str) -> "FissionFunction":
        package_name = func_name.replace(".", "")
        func_name = func_name.replace(".", "")
        logging.info(f"Deploying fission function...")
        function_cfg = FissionFunctionConfig.from_benchmark(code_package)
        function_cfg.storage = cast(Minio, self.get_storage()).config
        try:
            triggers = subprocess.run(
                f"fission fn list".split(), stdout=subprocess.PIPE, check=True
            )
            subprocess.run(
                f"grep {func_name}".split(),
                check=True,
                input=triggers.stdout,
                stdout=subprocess.DEVNULL,
            )
            res = FissionFunction(
                    func_name, code_package.benchmark, code_package.hash, 
                    function_cfg
                    )
            logging.info(f"Function {func_name} already exist")
            logging.info(f"Retrieved existing Fission function {func_name}.")
            self.update_function(res, code_package)
        except subprocess.CalledProcessError:
            subprocess.run(
                [
                  *self.get_fission_cmd(),
                  "fn",
                  "create",
                  "--name",
                  func_name,
                  "--pkg",
                  package_name,
                  "--ft",
                  str(code_package.benchmark_config.timeout * 1000),
                  "--maxmemory",
                  str(code_package.benchmark_config.memory),
                  "--entrypoint",
                  "handler.handler",
                ],
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
                check=True,
            )
            res = FissionFunction(
                    func_name, code_package.benchmark, code_package.hash, function_cfg
                    )
        return res

    def update_function(self, function: Function, code_package: Benchmark):
        self.logging.info(f"Update an existing Fission action {function.name}.")
        function = cast(FissionFunction, function)
        try:
            subprocess.run(
                    [
                        *self.get_fission_cmd(),
                        "fn",
                        "update",
                        "--name",
                        function.name,
                        "--src",
                        code_package.code_location, 
                        "--ft",
                        str(code_package.benchmark_config.timeout * 1000),
                        "--maxmemory",
                        str(code_package.benchmark_config.memory),
                        "--force"
                        ]
                    )
        except FileNotFoundError as e:
            self.logging.error("Could not update Fission function - is path to fission correct?")
            raise RuntimeError(e)

        except subprocess.CalledProcessError as e:
            self.logging.error(f"Unknown error when running function update: {e}!")
            self.logging.error("Make sure to remove SeBS cache after restarting Fission!")
            self.logging.error(f"Output: {e.stderr.decode('utf-8')}")
            raise RuntimeError(e)

    def update_function_configuration(self, function: Function, code_package: Benchmark):
        self.logging.info(f"Update configuration of an existing Fission action {function.name}.")
        try:
            subprocess.run(
                [
                    *self.get_fission_cmd(),
                    "fn",
                    "update",
                    "--name",
                    function.name,
                    "--maxmemory",
                    str(code_package.benchmark_config.memory),
                    "--ft",
                    str(code_package.benchmark_config.timeout * 1000),
                ],
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
                check=True,
            )
        except FileNotFoundError as e:
            self.logging.error("Could not update Fission function - is path to fission correct?")
            raise RuntimeError(e)
        except subprocess.CalledProcessError as e:
            self.logging.error(f"Unknown error when running function update: {e}!")
            self.logging.error("Make sure to remove SeBS cache after restarting Fisiion!")
            self.logging.error(f"Output: {e.stderr.decode('utf-8')}")
            raise RuntimeError(e)

     
    def is_configuration_changed(self, cached_function: Function, benchmark: Benchmark) -> bool:
        changed = super().is_configuration_changed(cached_function, benchmark)

        storage = cast(Minio, self.get_storage())
        function = cast(FissionFunction, cached_function)
        # check if now we're using a new storage
        if function.config.storage != storage.config:
            self.logging.info(
                "Updating function configuration due to changed storage configuration."
            )
            changed = True
            function.config.storage = storage.config

        return changed

    def default_function_name(self, code_package: Benchmark) -> str:
        return (
            f"{code_package.benchmark}-{code_package.language_name}-"
            f"{code_package.language_version}"
        )

    def enforce_cold_start(self, functions: List[Function], code_package: Benchmark):
        raise NotImplementedError()

    def download_metrics(
        self,
        function_name: str,
        start_time: int,
        end_time: int,
        requests: Dict[str, ExecutionResult],
        metrics: dict,
    ):
        pass

    def create_trigger(self, function: Function, trigger_type: Trigger.TriggerType) -> Trigger:
        triggerName = function.name + "trigger"
        triggerName = triggerName.replace("_", "")
        triggerName = triggerName.replace("-", "")
        postUrl = triggerName
        if trigger_type == Trigger.TriggerType.LIBRARY:
            self.logging.info("Library trigger is not supported in Fission as of now.")
            return function.triggers(Trigger.TriggerType.LIBRARY)[0]
        elif trigger_type == Trigger.TriggerType.HTTP:
            try:
                triggers = subprocess.run(
                f"fission httptrigger list".split(), stdout=subprocess.PIPE, check=True
                )
                subprocess.run(
                        f"grep {triggerName}".split(),
                        check=True,
                        input=triggers.stdout,
                        stdout=subprocess.DEVNULL,)
                logging.info(f"Trigger {triggerName} already exist")
            except subprocess.CalledProcessError:
                subprocess.run(
                f"fission httptrigger create --method POST --url /{postUrl} --function {function.name} --name {triggerName}".split(),
                check=True,
            )
            # PK: do not encode url , get this from config specified by User. The defualt in config will be localhost and 31314
            url = "http://localhost:31314" + "/" + postUrl
            trigger = HTTPTrigger(function.name, url)
            trigger.logging_handlers = self.logging_handlers
            function.add_trigger(trigger)
            self.cache_client.update_function(function)
            return trigger
        else:
            raise RuntimeError("Not supported!")

    def cached_function(self, function: Function):
        for trigger in function.triggers(Trigger.TriggerType.LIBRARY):
            trigger.logging_handlers = self.logging_handlers
            cast(LibraryTrigger, trigger).fission_cmd = self.get_fission_cmd()
        for trigger in function.triggers(Trigger.TriggerType.HTTP):
            trigger.logging_handlers = self.logging_handlers
