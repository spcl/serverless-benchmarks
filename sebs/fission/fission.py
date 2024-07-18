import logging
import os
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
from sebs.faas.function import Function, Trigger, ExecutionResult
from sebs.faas.system import System
from sebs.utils import DOCKER_DIR, LoggingHandlers, execute
# from sebs.fission.fissionFunction import FissionFunction
from sebs.benchmark import Benchmark
from sebs.fission.config import FissionConfig
from sebs.fission.storage import Minio
from .function import FissionFunction, FissionFunctionConfig

from tools.fission_preparation import (
    check_if_minikube_installed,
    run_minikube,
    check_if_k8s_installed,
    check_if_helm_installed,
    stop_minikube,
)


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
    
    # not sure waht is this
    def get_fission_cmd(self) -> List[str]:
        cmd = [self.config.fission_exec]
        # if self.config.wsk_bypass_security:
        #     cmd.append("-i")
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
        print("the build base iamge")
        """
        When building function for the first time (according to SeBS cache),
        check if Docker image is available in the registry.
        If yes, then skip building.
        If no, then continue building.

        For every subsequent build, we rebuild image and push it to the
        registry. These are triggered by users modifying code and enforcing
        a build.
        """

        # We need to retag created images when pushing to registry other
        # than default
        registry_name = self.config.resources.docker_registry
        repository_name = self.system_config.docker_repository()
        image_tag = self.system_config.benchmark_image_tag(
            self.name(), benchmark, language_name, language_version
        )
        if registry_name is not None and registry_name != "":
            repository_name = f"{registry_name}/{repository_name}"
        else:
            registry_name = "Docker Hub"

        # Check if we the image is already in the registry.
        # cached package, rebuild not enforced -> check for new one
        if is_cached:
            if self.find_image(repository_name, image_tag):
                self.logging.info(
                    f"Skipping building Fission Docker package for {benchmark}, using "
                    f"Docker image {repository_name}:{image_tag} from registry: "
                    f"{registry_name}."
                )
                return False
            else:
                # image doesn't exist, let's continue
                self.logging.info(
                    f"Image {repository_name}:{image_tag} doesn't exist in the registry, "
                    f"building Fission package for {benchmark}."
                )

        build_dir = os.path.join(directory, "docker")
        os.makedirs(build_dir, exist_ok=True)
        shutil.copy(
            os.path.join(DOCKER_DIR, self.name(), language_name, "Dockerfile.function"),
            os.path.join(build_dir, "Dockerfile"),
        )

        for fn in os.listdir(directory):
            if fn not in ("index.js", "__main__.py"):
                file = os.path.join(directory, fn)
                shutil.move(file, build_dir)

        with open(os.path.join(build_dir, ".dockerignore"), "w") as f:
            f.write("Dockerfile")

        builder_image = self.system_config.benchmark_base_images(self.name(), language_name)[
            language_version
        ]
        self.logging.info(f"Build the benchmark base image {repository_name}:{image_tag}.")
        print("THE BUIDER Image is", builder_image)

        buildargs = {"VERSION": language_version, "BASE_IMAGE": builder_image}
        print(f"{repository_name}:{image_tag}")
        print("Build dir is", build_dir)
        print("Build Argument is", buildargs)
        image, _ = self.docker_client.images.build(
            tag=f"{repository_name}:{image_tag}", path=build_dir, buildargs=buildargs
        )

        # Now push the image to the registry
        # image will be located in a private repository
        self.logging.info(
            f"Push the benchmark base image {repository_name}:{image_tag} "
            f"to registry: {registry_name}."
        )

        # PK: PUshing the Image function is not implemented as of now 

        # ret = self.docker_client.images.push(
        #     repository=repository_name, tag=image_tag, stream=True, decode=True
        # )
        # # doesn't raise an exception for some reason
        # for val in ret:
        #     if "error" in val:
        #         self.logging.error(f"Failed to push the image to registry {registry_name}")
        #         raise RuntimeError(val)
        return True

    def update_build_script(self, scriptPath):
        build_script_path = scriptPath + "/"  + "build.sh"
        print("the build script pathh is", build_script_path)
        subprocess.run(["chmod", "+x", build_script_path])

    def create_zip_directory_fission(directory):
        pass

    # packaging code will be differend
    def package_code(
        self,
        directory: str,
        language_name: str,
        language_version: str,
        benchmark: str,
        is_cached: bool,
    ) -> Tuple[str, int]:

        # self.build_base_image(directory, language_name, language_version, benchmark, is_cached)

        # repo_name = self._system_config.docker_repository()
        # image_name = "build.{deployment}.{language}.{runtime}".format(
        #         deployment=self._deployment_name,
        #         language=language_name,
        #         runtime=language_version,
        #     )
        print("DOM SOMETHIGN AFTERTHEE BASE IAMGE")
        print("THE BENCHMARK IS", benchmark)
        # FIrst we will create an encviroment here
        # 3 paramters 
        # name : langauge
        enviroment_name = language_name + language_version.replace(".","")
        print("THE ENVVVVV name is", enviroment_name)
        builder_image = self.system_config.benchmark_base_images(self.name(), language_name)[
            language_version
        ]
        builder_image = "spcleth/serverless-benchmarks:build.fission.python.3.8"
        runtime_image = builder_image 

        # First we need to create the enviroment 
        print("the run tiume ", runtime_image)
        print("The builder is", builder_image)

        self.config.resources.create_enviroment(name = enviroment_name, image = runtime_image,  builder = builder_image)
        print("The directory is", directory)
        self.update_build_script(directory)

        # After Creating enviroment we need to create the package. 
        # For creating package, we need to create a zip file with the code and dependency. 
        # PK: I tried zipping the depenecy and using that but it does niot seem to work on fission so we need to build it again 


        # We deploy Minio config in code package since this depends on local
        # deployment - it cannnot be a part of Docker image
        CONFIG_FILES = {
            "python": ["__main__.py"],
            "nodejs": ["index.js"],
        }
        package_config = CONFIG_FILES[language_name]

        benchmark_archive = os.path.join(directory, f"{benchmark}.zip")
        # directory =  directory + "/" + "docker"
        zip_command = [
            "zip",
            "-r",
            benchmark_archive,
            ".",
            "-x",
            ".python_packages/*"
        ]

        subprocess.run(
            zip_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=directory,
            text=True
        )
        # zip -r benchmark_archive directory -x "docker/.python_packages/*"
        # subprocess.run(
        #     ["zip -r", benchmark_archive] + package_config, stdout=subprocess.PIPE,    stderr=subprocess.PIPE, cwd=directory
        # )
        # exit(0)
        self.logging.info(f"Created {benchmark_archive} archive")
        bytes_size = os.path.getsize(benchmark_archive)
        self.logging.info("Zip archive size {:2f} MB".format(bytes_size / 1024.0 / 1024.0))
        print(benchmark_archive)
        print(bytes_size)
        print("AT the end of code package packaging")

        # Second we need to create the package , for creating the package we will use the zip file we have just created
        package_name = benchmark  + "-" + language_name + "-" + language_version 
        package_name = package_name.replace(".","")
        print(package_name)
        self.config.resources.create_package(package_name = package_name, path = benchmark_archive, env_name = enviroment_name)


        print("FIRST ARE WE IN herhe building the IMAGEJFKSFJDKJF")
        return benchmark_archive, bytes_size

    def storage_arguments(self) -> List[str]:
        storage = cast(Minio, self.get_storage())
        return [
            "-p",
            "MINIO_STORAGE_SECRET_KEY",
            storage.config.secret_key,
            "-p",
            "MINIO_STORAGE_ACCESS_KEY",
            storage.config.access_key,
            "-p",
            "MINIO_STORAGE_CONNECTION_URL",
            storage.config.address,
        ] 


    def create_function(self, code_package: Benchmark, func_name: str) -> "FissionFunction":
        package_name = func_name.replace(".", "")
        func_name = func_name.replace(".", "")
        # triggerName = f"{func_name}-trigger"
        # self.functionName = func_name 
        # self.httpTriggerName = triggerName
        print("DEPLOYTING FIssin fnc")
        logging.info(f"Deploying fission function...")
        function_cfg = FissionFunctionConfig.from_benchmark(code_package)
        function_cfg.storage = cast(Minio, self.get_storage()).config
        print("DEPLOYTING FIssin fnc after some fnconfig thing")
        try:
            print("In the try BLock")
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
            # PK: Need to do: self.update_function(res, code_package)
            print("Fission function already exsit")
            logging.info(f"Function {func_name} already exist")
        except subprocess.CalledProcessError:
            print("Before except")
            # subprocess.run(
            #     [
            #       *self.get_fission_cmd(),
            #       "fn",
            #       "create",
            #       "--name",
            #       func_name,
            #       "--pkg",
            #       package_name,
            #       "--entrypoint",
            #       "function.handler",
            #       "--fntimeout",
            #       next(iter({str(code_package.benchmark_config.timeout)})),
            #       "--maxmemory",
            #       next(iter({str(code_package.benchmark_config.memory)}))
            #     ],
            #     stderr=subprocess.PIPE,
            #     stdout=subprocess.PIPE,
            #     check=True,
            # )
            #
            subprocess.run(
                [
                  *self.get_fission_cmd(),
                  "fn",
                  "create",
                  "--name",
                  func_name,
                  "--pkg",
                  package_name,
                  "--entrypoint",
                  "function.handler",
                  "--fntimeout",
                  '30000000000',
                  "--maxmemory",
                  next(iter({str(code_package.benchmark_config.memory)}))
                ],
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
                check=True,
            )
            print("Afer except")
            res = FissionFunction(
                    func_name, code_package.benchmark, code_package.hash, function_cfg
                    )
        # PK:########## ADDING TRIGGERs
        # try:
        #     triggers = subprocess.run(
        #         f"fission httptrigger list".split(), stdout=subprocess.PIPE, check=True
        #     )
        #     subprocess.run(
        #         f"grep {triggerName}".split(),
        #         check=True,
        #         input=triggers.stdout,
        #         stdout=subprocess.DEVNULL,
        #     )
        #     logging.info(f"Trigger {triggerName} already exist")
        # except subprocess.CalledProcessError:
        #     subprocess.run(
        #         f"fission httptrigger create --url /benchmark --method POST \
        #         --name {triggerName} --function {name}".split(),
        #         check=True,
        #     )

        # self.logging.info("Creating function as an action in Fission.")
        # try:
        #     actions = subprocess.run(
        #         [*self.get_wsk_cmd(), "action", "list"],
        #         stderr=subprocess.DEVNULL,
        #         stdout=subprocess.PIPE,
        #     )
        #
        #     function_found = False
        #     docker_image = ""
        #     for line in actions.stdout.decode().split("\n"):
        #         if line and func_name in line.split()[0]:
        #             function_found = True
        #             break
        #
        #     function_cfg = FissionConfig.from_benchmark(code_package)
        #     function_cfg.storage = cast(Minio, self.get_storage()).config
        #     if function_found:
        #         # docker image is overwritten by the update
        #         res = FissionFunction(
        #             func_name, code_package.benchmark, code_package.hash, function_cfg
        #         )
        #         # Update function - we don't know what version is stored
        #         self.logging.info(f"Retrieved existing fission action {func_name}.")
        #         self.update_function(res, code_package)
        #     else:
        #         try:
        #             self.logging.info(f"Creating new FissionF action {func_name}")
        #             docker_image = self.system_config.benchmark_image_name(
        #                 self.name(),
        #                 code_package.benchmark,
        #                 code_package.language_name,
        #                 code_package.language_version,
        #             )
        #             subprocess.run(
        #                 [
        #                     *self.get_wsk_cmd(),
        #                     "action",
        #                     "create",
        #                     func_name,
        #                     "--web",
        #                     "true",
        #                     "--docker",
        #                     docker_image,
        #                     "--memory",
        #                     str(code_package.benchmark_config.memory),
        #                     "--timeout",
        #                     str(code_package.benchmark_config.timeout * 1000),
        #                     *self.storage_arguments(),
        #                     code_package.code_location,
        #                 ],
        #                 stderr=subprocess.PIPE,
        #                 stdout=subprocess.PIPE,
        #                 check=True,
        #             )
        #             function_cfg.docker_image = docker_image
        #             res = FissionFunction(
        #                 func_name, code_package.benchmark, code_package.hash, function_cfg
        #             )
        #         except subprocess.CalledProcessError as e:
        #             self.logging.error(f"Cannot create action {func_name}.")
        #             self.logging.error(f"Output: {e.stderr.decode('utf-8')}")
        #             raise RuntimeError(e)
        #
        # except FileNotFoundError:
        #     self.logging.error("Could not retrieve Fission functions - is path to wsk correct?")
        #     raise RuntimeError("Failed to access wsk binary")
        #
        # # Add LibraryTrigger to a new function
        # trigger = LibraryTrigger(func_name, self.get_wsk_cmd())
        # trigger.logging_handlers = self.logging_handlers
        # res.add_trigger(trigger)
        #
        return res

    def update_function(self, function: Function, code_package: Benchmark):
        self.logging.info(f"Update an existing Fission action {function.name}.")
        function = cast(FissionFunction, function)
        docker_image = self.system_config.benchmark_image_name(
            self.name(),
            code_package.benchmark,
            code_package.language_name,
            code_package.language_version,
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
                    *self.storage_arguments(),
                    code_package.code_location,
                ],
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
                check=True,
            )
            function.config.docker_image = docker_image

        except FileNotFoundError as e:
            self.logging.error("Could not update Fission function - is path to wsk correct?")
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
                    *self.get_wsk_cmd(),
                    "action",
                    "update",
                    function.name,
                    "--memory",
                    str(code_package.benchmark_config.memory),
                    "--timeout",
                    str(code_package.benchmark_config.timeout * 1000),
                    *self.storage_arguments(),
                ],
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
                check=True,
            )
        except FileNotFoundError as e:
            self.logging.error("Could not update Fission function - is path to wsk correct?")
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

    # def create_trigger(self, function: Function, trigger_type: Trigger.TriggerType) -> Trigger:
    #     print("THE TRIGGER TYPE IS", trigger_type)
    #     if trigger_type == Trigger.TriggerType.LIBRARY:
    #         return function.triggers(Trigger.TriggerType.LIBRARY)[0]
    #
    #     elif trigger_type == Trigger.TriggerType.HTTP:
    #         try:
    #             triggers = subprocess.run(
    #             f"fission httptrigger list".split(), stdout=subprocess.PIPE,
    #             check=True
    #         )
    #         subprocess.run(
    #             f"grep {triggerName}".split(),
    #             check=True,
    #             input=triggers.stdout,
    #             stdout=subprocess.DEVNULL,
    #         )
    #         logging.info(f"Trigger {triggerName} already exist")
    #
    #         except subprocess.CalledProcessError:
    #             subprocess.run(
    #             f"fission httptrigger create --url /benchmark --method POST \
    #             --name {triggerName} --function {name}".split(),
    #             check=True,
    #         )
    #

    def create_trigger(self, function: Function, trigger_type: Trigger.TriggerType) -> Trigger:
        print("THE TRIGGER TYPE IS", trigger_type)
        print("THE Function is", function.name)
        triggerName = function.name + "call"
        triggerName = triggerName.replace("_", "")
        triggerName = triggerName.replace("-", "")
        print("THE Trigger Name is", triggerName)
        if trigger_type == Trigger.TriggerType.LIBRARY:
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
                # response = subprocess.run(
                #     [*self.get_wsk_cmd(), "action", "get", function.name, "--url"],
                #     stdout=subprocess.PIPE,
                #     stderr=subprocess.DEVNULL,
                #     check=True,
                # )
            except subprocess.CalledProcessError:
                subprocess.run(
                f"fission httptrigger create --url /benchmark --method POST \
                --name {triggerName} --function {function.name}".split(),
                check=True,
            )
            # except FileNotFoundError as e:
            #     self.logging.error(
            #         "Could not retrieve Fission configuration - is path to wsk correct?"
            #     )
            #     raise RuntimeError(e)
            stdout = response.stdout.decode("utf-8")
            print("THE stodout is", stdout)
            url = stdout.strip().split("\n")[-1] + ".json"
            print("utl", url)
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
            cast(LibraryTrigger, trigger).wsk_cmd = self.get_wsk_cmd()
        for trigger in function.triggers(Trigger.TriggerType.HTTP):
            trigger.logging_handlers = self.logging_handlers



#     @staticmethod
#     def name():
#         return "fission"
#
#     @property
#     def config(self) -> FissionConfig:
#         return self._config
#
#     @staticmethod
#     def add_port_forwarding(port=5051):
#         podName = (
#             subprocess.run(
#                 f"kubectl --namespace fission get pod -l svc=router -o name".split(),
#                 stdout=subprocess.PIPE,
#             )
#             .stdout.decode("utf-8")
#             .rstrip()
#         )
#         subprocess.Popen(
#             f"kubectl --namespace fission port-forward {podName} {port}:8888".split(),
#             stderr=subprocess.DEVNULL,
#         )
#
#     def shutdown(self) -> None:
#         if self.config.shouldShutdown:
#             if hasattr(self, "httpTriggerName"):
#                 subprocess.run(f"fission httptrigger delete --name {self.httpTriggerName}".split())
#             if hasattr(self, "functionName"):
#                 subprocess.run(f"fission fn delete --name {self.functionName}".split())
#             if hasattr(self, "packageName"):
#                 subprocess.run(f"fission package delete --name {self.packageName}".split())
#             if hasattr(self, "envName"):
#                 subprocess.run(f"fission env delete --name {self.envName}".split())
#             stop_minikube()
#         self.storage.storage_container.kill()
#         logging.info("Minio stopped")
#
#     def get_storage(self, replace_existing: bool = False) -> PersistentStorage:
#         self.storage = Minio(self.docker_client)
#         return self.storage
#
#     def initialize(self, config: Dict[str, str] = None):
#         if config is None:
#             config = {}
#
#         check_if_minikube_installed()
#         check_if_k8s_installed()
#         check_if_helm_installed()
#         run_minikube()
#         Fission.add_port_forwarding()
#         sleep(5)
#
#     def package_code(self, benchmark: Benchmark) -> Tuple[str, int]:
#
#         benchmark.build()
#
#         CONFIG_FILES = {
#             "python": [
#                 "handler.py",
#                 "requirements.txt",
#                 ".python_packages",
#                 "build.sh",
#             ],
#             "nodejs": ["handler.js", "package.json", "node_modules"],
#         }
#         directory = benchmark.code_location
#         package_config = CONFIG_FILES[benchmark.language_name]
#         function_dir = os.path.join(directory, "function")
#         os.makedirs(function_dir)
#         minioConfig = open("./code/minioConfig.json", "w+")
#         minioConfigJson = {
#             "access_key": self.storage.access_key,
#             "secret_key": self.storage.secret_key,
#             "url": self.storage.url,
#         }
#         minioConfig.write(json.dumps(minioConfigJson))
#         minioConfig.close()
#         scriptPath = os.path.join(directory, "build.sh")
#         self.shouldCallBuilder = True
#         f = open(scriptPath, "w+")
#         f.write(
#             "#!/bin/sh\npip3 install -r ${SRC_PKG}/requirements.txt -t \
# ${SRC_PKG} && cp -r ${SRC_PKG} ${DEPLOY_PKG}"
#         )
#         f.close()
#         subprocess.run(["chmod", "+x", scriptPath])
#         for file in os.listdir(directory):
#             if file not in package_config:
#                 file = os.path.join(directory, file)
#                 shutil.move(file, function_dir)
#         os.chdir(directory)
#         subprocess.run(
#             "zip -r {}.zip ./".format(benchmark.benchmark).split(),
#             stdout=subprocess.DEVNULL,
#         )
#         benchmark_archive = "{}.zip".format(os.path.join(directory, benchmark.benchmark))
#         logging.info("Created {} archive".format(benchmark_archive))
#         bytes_size = os.path.getsize(benchmark_archive)
#         return benchmark_archive, bytes_size
#
#     def update_function(self, name: str, env_name: str, code_path: str):
#         self.create_function(name, env_name, code_path)
#
#     def create_env_if_needed(self, name: str, image: str, builder: str):
#         self.envName = name
#         try:
#             fission_env_list = subprocess.run(
#                 "fission env list ".split(),
#                 stdout=subprocess.PIPE,
#                 stderr=subprocess.DEVNULL,
#             )
#             subprocess.run(
#                 f"grep {name}".split(),
#                 check=True,
#                 stdout=subprocess.DEVNULL,
#                 stderr=subprocess.DEVNULL,
#                 input=fission_env_list.stdout,
#             )
#             logging.info(f"Env {name} already exist")
#         except subprocess.CalledProcessError:
#             logging.info(f'Creating env for {name} using image "{image}".')
#             try:
#                 subprocess.run(
#                     f"fission env create --name {name} --image {image} \
#                     --builder {builder}".split(),
#                     check=True,
#                     stdout=subprocess.DEVNULL,
#                 )
#             except subprocess.CalledProcessError:
#                 logging.info(f"Creating env {name} failed. Retrying...")
#                 sleep(10)
#                 try:
#                     subprocess.run(
#                         f"fission env create --name {name} --image {image} \
#                         --builder {builder}".split(),
#                         check=True,
#                         stdout=subprocess.DEVNULL,
#                     )
#                 except subprocess.CalledProcessError:
#                     self.storage.storage_container.kill()
#                     logging.info("Minio stopped")
#                     self.initialize()
#                     self.create_env_if_needed(name, image, builder)
#
#     def create_function(self, name: str, env_name: str, path: str):
#         packageName = f"{name}-package"
#         self.createPackage(packageName, path, env_name)
#         self.createFunction(packageName, name)
#
#     def createPackage(self, packageName: str, path: str, envName: str) -> None:
#         logging.info(f"Deploying fission package...")
#         self.packageName = packageName
#         try:
#             packages = subprocess.run(
#                 "fission package list".split(), stdout=subprocess.PIPE, check=True
#             )
#             subprocess.run(
#                 f"grep {packageName}".split(),
#                 check=True,
#                 input=packages.stdout,
#                 stdout=subprocess.DEVNULL,
#             )
#             logging.info("Package already exist")
#         except subprocess.CalledProcessError:
#             process = f"fission package create --sourcearchive {path} \
#             --name {packageName} --env {envName} --buildcmd ./build.sh"
#             subprocess.run(process.split(), check=True)
#             logging.info("Waiting for package build...")
#             while True:
#                 try:
#                     packageStatus = subprocess.run(
#                         f"fission package info --name {packageName}".split(),
#                         stdout=subprocess.PIPE,
#                     )
#                     subprocess.run(
#                         f"grep succeeded".split(),
#                         check=True,
#                         input=packageStatus.stdout,
#                         stderr=subprocess.DEVNULL,
#                     )
#                     break
#                 except subprocess.CalledProcessError:
#                     if "failed" in packageStatus.stdout.decode("utf-8"):
#                         logging.error("Build package failed")
#                         raise Exception("Build package failed")
#                     sleep(3)
#                     continue
#             logging.info("Package ready")
#
#     def deletePackage(self, packageName: str) -> None:
#         logging.info(f"Deleting fission package...")
#         subprocess.run(f"fission package delete --name {packageName}".split())
#
#     def createFunction(self, packageName: str, name: str) -> None:
#         triggerName = f"{name}-trigger"
#         self.functionName = name
#         self.httpTriggerName = triggerName
#         logging.info(f"Deploying fission function...")
#         try:
#             triggers = subprocess.run(
#                 f"fission fn list".split(), stdout=subprocess.PIPE, check=True
#             )
#             subprocess.run(
#                 f"grep {name}".split(),
#                 check=True,
#                 input=triggers.stdout,
#                 stdout=subprocess.DEVNULL,
#             )
#             logging.info(f"Function {name} already exist")
#         except subprocess.CalledProcessError:
#             subprocess.run(
#                 f"fission fn create --name {name} --pkg {packageName} \
#                     --entrypoint handler.handler --env {self.envName}".split(),
#                 check=True,
#             )
#         try:
#             triggers = subprocess.run(
#                 f"fission httptrigger list".split(), stdout=subprocess.PIPE, check=True
#             )
#             subprocess.run(
#                 f"grep {triggerName}".split(),
#                 check=True,
#                 input=triggers.stdout,
#                 stdout=subprocess.DEVNULL,
#             )
#             logging.info(f"Trigger {triggerName} already exist")
#         except subprocess.CalledProcessError:
#             subprocess.run(
#                 f"fission httptrigger create --url /benchmark --method POST \
#                 --name {triggerName} --function {name}".split(),
#                 check=True,
#             )
#
#     def deleteFunction(self, name: str) -> None:
#         logging.info(f"Deleting fission function...")
#         subprocess.run(f"fission fn delete --name {name}".split())
#
#     def get_function(self, code_package: Benchmark) -> Function:
#         self.language_image = self.system_config.benchmark_base_images(
#             self.name(), code_package.language_name
#         )["env"]
#         self.language_builder = self.system_config.benchmark_base_images(
#             self.name(), code_package.language_name
#         )["builder"]
#         path, size = self.package_code(code_package)
#         benchmark = code_package.benchmark.replace(".", "-")
#         language = code_package.language_name
#         language_runtime = code_package.language_version
#         timeout = code_package.benchmark_config.timeout
#         memory = code_package.benchmark_config.memory
#         if code_package.is_cached and code_package.is_cached_valid:
#             func_name = code_package.cached_config["name"]
#             code_location = os.path.join(
#                 code_package._cache_client.cache_dir,
#                 code_package._cached_config["code"],
#             )
#             logging.info(
#                 "Using cached function {fname} in {loc}".format(fname=func_name, loc=code_location)
#             )
#             self.create_env_if_needed(
#                 language,
#                 self.language_image,
#                 self.language_builder,
#             )
#             self.update_function(func_name, code_package.language_name, path)
#             return FissionFunction(func_name)
#         elif code_package.is_cached:
#             func_name = code_package.cached_config["name"]
#             code_location = code_package.code_location
#             self.create_env_if_needed(
#                 language,
#                 self.language_image,
#                 self.language_builder,
#             )
#             self.update_function(func_name, code_package.language_name, path)
#             cached_cfg = code_package.cached_config
#             cached_cfg["code_size"] = size
#             cached_cfg["timeout"] = timeout
#             cached_cfg["memory"] = memory
#             cached_cfg["hash"] = code_package.hash
#             self.cache_client.update_function(
#                 self.name(),
#                 benchmark.replace("-", "."),
#                 code_package.language_name,
#                 path,
#                 cached_cfg,
#             )
#             code_package.query_cache()
#             logging.info(
#                 "Updating cached function {fname} in {loc}".format(
#                     fname=func_name, loc=code_location
#                 )
#             )
#             return FissionFunction(func_name)
#         else:
#             code_location = code_package.benchmark_path
#             func_name = "{}-{}-{}".format(benchmark, language, memory)
#             self.create_env_if_needed(
#                 language,
#                 self.language_image,
#                 self.language_builder,
#             )
#             self.create_function(func_name, language, path)
#             self.cache_client.add_function(
#                 deployment=self.name(),
#                 benchmark=benchmark.replace("-", "."),
#                 language=language,
#                 code_package=path,
#                 language_config={
#                     "name": func_name,
#                     "code_size": size,
#                     "runtime": language_runtime,
#                     "memory": memory,
#                     "timeout": timeout,
#                     "hash": code_package.hash,
#                 },
#                 storage_config={
#                     "buckets": {
#                         "input": self.storage.input_buckets,
#                         "output": self.storage.output_buckets,
#                     }
#                 },
#             )
#             code_package.query_cache()
#             return FissionFunction(func_name)
