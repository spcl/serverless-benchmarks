import logging
import os
import shutil
import subprocess
import docker
from typing import Dict, Tuple
from sebs.faas.storage import PersistentStorage
from sebs.cache import Cache
from sebs.config import SeBSConfig
from sebs.faas.function import Function
from sebs.faas.system import System
from sebs.fission.fissionFunction import FissionFunction
from sebs.benchmark import Benchmark
from sebs.fission.config import FissionConfig
from sebs.fission.minio import Minio
from sebs import utils

class Fission(System):
    available_languages_images = {"python": "fission/python-env:latest", "nodejs": "fission/node-env:latest"}
    available_languages_builders = {"python": "fission/python-builder:latest", "nodejs": "fission/node-builder:latest"}
    storage : Minio
    httpTriggerName: str
    functionName: str
    packageName: str
    envName: str
    _config : FissionConfig
    def __init__(
        self, sebs_config: SeBSConfig, config: FissionConfig, cache_client: Cache, docker_client: docker.client
    ):
        super().__init__(sebs_config, cache_client, docker_client)
        self._added_functions: [str] = []
        self._config = config

    @staticmethod
    def name():
        return "fission"

    @property
    def config(self) -> FissionConfig:
        return self._config

    @staticmethod
    def check_if_minikube_installed():
        try:
            subprocess.run('minikube version'.split(), check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            logging.error("ERROR: \"minikube\" required.")

    @staticmethod
    def run_minikube(vm_driver='docker'):
        try:
            kube_status = subprocess.run('minikube status'.split(), stdout=subprocess.PIPE)

            #if minikube is already running, error will be raised to prevent to be started minikube again.
            subprocess.run(
                'grep Stopped'.split(),
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                input=kube_status.stdout
            )
            try:
                logging.info('Starting minikube...')
                subprocess.run(f'minikube start --vm-driver={vm_driver}'.split(), check=True)
            except subprocess.CalledProcessError:
                raise ChildProcessError

        except subprocess.CalledProcessError:
            try:
                subprocess.run(
                'grep unusually'.split(),
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                input=kube_status.stdout
            )
                logging.info('Starting minikube...')
                subprocess.run(f'minikube start --vm-driver={vm_driver}'.split(), check=True)
            except subprocess.CalledProcessError:
                logging.info('Minikube already working')
            pass
        except ChildProcessError:
            logging.error("ERROR: COULDN'T START MINIKUBE")
            exit(1)

    @staticmethod
    def check_if_k8s_installed():
        try:
            subprocess.run('kubectl version'.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        except subprocess.CalledProcessError:
            logging.error("ERROR: \"kubectl\" required.")

    @staticmethod
    def check_if_helm_installed():
        try:
            subprocess.run('helm version'.split(), check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            logging.error("ERROR: \"helm\" required.")

    @staticmethod
    def install_fission_using_helm(k8s_namespace='fission'):
        fission_url = 'https://github.com/fission/fission/releases/download/1.9.0/fission-all-1.9.0.tgz'

        try:
            k8s_namespaces = subprocess.run(
                'kubectl get namespace'.split(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
            subprocess.run(
                f'grep {k8s_namespace}'.split(),
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                input=k8s_namespaces.stdout
            )
            logging.info('fission namespace already exist')
        except (subprocess.CalledProcessError):
            logging.info(f'No proper fission namespace... Installing Fission as \"{k8s_namespace}\"...')
            subprocess.run(
                f'kubectl create namespace {k8s_namespace}'.split(), check=True
            )
            subprocess.run(
                f'helm install --namespace {k8s_namespace} --name-template fission {fission_url}'.split(), check=True
            )

    @staticmethod
    def install_fission_cli_if_needed():
        try:
            subprocess.run(['fission'], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=True)
        except subprocess.CalledProcessError:  # if raised - fission cli is not installed
            logging.info("No fission CLI - installing...")
            available_os = {
                'darwin': 'osx',
                'linux': 'linux'
            }
            import platform
            fission_cli_url = f'https://github.com/fission/fission/releases/download/1.9.0/fission-cli-' \
                              f'{available_os[platform.system().lower()]}'

            subprocess.run(
                f'curl -Lo fission {fission_cli_url} && chmod +x fission && sudo mv fission /usr/local/bin/',
                stdout=subprocess.DEVNULL, check=True, shell=True
            )

    def shutdown(self) -> None:
        subprocess.run(f'fission httptrigger delete --name {self.httpTriggerName}'.split())
        subprocess.run(f'fission fn delete --name {self.functionName}'.split())
        subprocess.run(f'fission package delete --name {self.packageName}'.split())
        subprocess.run(f'fission env delete --name {self.envName}'.split())

    def get_storage(self, replace_existing: bool = False) -> PersistentStorage:
        self.storage = Minio(self.docker_client)
        return self.storage

    def initialize(self, config: Dict[str, str] = None):
        if config is None:
            config = {}

        Fission.check_if_minikube_installed()
        Fission.run_minikube()
        Fission.check_if_k8s_installed()
        Fission.check_if_helm_installed()
        Fission.install_fission_using_helm()
        Fission.install_fission_cli_if_needed()

    def package_code(self, benchmark: Benchmark) -> Tuple[str, int]:
        CONFIG_FILES = {
            "python": ["handler.py", "requirements.txt", ".python_packages"],
            "nodejs": ["handler.js", "package.json", "node_modules"],
        }
        directory = benchmark.benchmark_path
        package_config = CONFIG_FILES[benchmark.language_name]
        os.chdir(directory)
        subprocess.run("zip -jr {}.zip {}/".format(benchmark.benchmark, benchmark.language_name).split(), stdout=subprocess.DEVNULL)
        benchmark_archive = "{}.zip".format(
            os.path.join(directory, benchmark.benchmark)
        )
        logging.info("Created {} archive".format(benchmark_archive))
        bytes_size = os.path.getsize(os.path.join(directory, benchmark.language_name))
        return benchmark_archive, bytes_size

    def update_function(self, name: str, env_name: str, code_path: str):
        packageName = f'{name}-package'
        self.deleteFunction(name)
        self.deletePackage(packageName)
        self.createPackage(packageName, code_path, )

    def create_env_if_needed(self, name: str, image: str, builder: str):
        try:
            fission_env_list = subprocess.run(
                'fission env list '.split(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )

            subprocess.run(
                f'grep {name}'.split(),
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                input=fission_env_list.stdout
            )
            self.envName = name
        except subprocess.CalledProcessError:  # if exception raised it means that there is no appropriate namespace
            logging.info(f'Creating env for {name} using image \"{image}\".')
            self.envName = name
            subprocess.run(
                f'fission env create --name {name} --image {image} --builder {builder}'.split(),
                check=True, stdout=subprocess.DEVNULL
            )

    def create_function(self, name: str, env_name: str, path: str):
        packageName = f'{name}-package'
        try:
            packages = subprocess.run('fission package list'.split(), stdout=subprocess.PIPE, check=True)
            subprocess.run(
                f'grep {packageName}'.split(),
                check=True,
                input=packages.stdout
            )
            try:
                self.deleteFunction(name)
                self.deletePackage(packageName)
                self.createPackage(packageName, path, env_name)
                functions = subprocess.run('fission function list'.split(), stdout=subprocess.PIPE, check=True)
                subprocess.run(
                f'grep {name}'.split(),
                check=True,
                input=functions.stdout
            )
            except subprocess.CalledProcessError:
                self.createFunction(packageName, name)
        except subprocess.CalledProcessError:
            self.createPackage(packageName, path, env_name)
            self.createFunction(packageName, name)


    def createPackage(self, packageName: str, path: str, envName: str) -> None:
        logging.info(f'Deploying fission package...')
        self.packageName = packageName
        subprocess.run(f'fission package create --deployarchive {path} --name {packageName} --env {envName}'.split(), check=True)
    
    def deletePackage(self, packageName: str) -> None:
        logging.info(f'Deleting fission package...')
        subprocess.run(f'fission package delete --name {packageName}'.split())

    def createFunction(self, packageName: str, name: str) -> None:
        logging.info(f'Deploying fission function...')
        subprocess.run(
            f'fission fn create --name {name} --pkg {packageName} --entrypoint function.handler'.split(), check=True
        )
        triggerName = f'{name}-trigger'
        self.functionName = name
        self.httpTriggerName = triggerName
        try:
            triggers = subprocess.run(f'fission httptrigger list'.split(), stdout=subprocess.PIPE, check=True)
            subprocess.run(
                    f'grep {triggerName}'.split(),
                    check=True,
                    input=triggers.stdout
                )
        except subprocess.CalledProcessError:
            subprocess.run(f'fission httptrigger create --url /benchmark --method GET --name {triggerName} --function {name}'.split(), check=True)

    def deleteFunction(self, name: str)-> None:
        logging.info(f'Deleting fission function...')
        subprocess.run(f'fission fn delete --name {name}'.split())
    
    def get_function(self, code_package: Benchmark) -> Function:
        path, size = self.package_code(code_package)

        # TODO: also exception if language not in self.available_languages_images
        if (
            code_package.language_version
            not in self.system_config.supported_language_versions(
                self.name(), code_package.language_name
            )
        ):
            raise Exception(
                "Unsupported {language} version {version} in Fission!".format(
                    language=code_package.language_name,
                    version=code_package.language_version,
                )
            )
        benchmark = code_package.benchmark.replace('.','-')
        language = code_package.language_name
        language_runtime = code_package.language_version
        timeout = code_package.benchmark_config.timeout
        memory = code_package.benchmark_config.memory
        if code_package.is_cached and code_package.is_cached_valid:
            func_name = code_package.cached_config["name"]
            code_location = code_package.code_location
            logging.info(
                "Using cached function {fname} in {loc}".format(
                    fname=func_name, loc=code_location
                )
            )
            self.create_env_if_needed(language, self.available_languages_images[language], self.available_languages_builders[language])
            self.create_function(func_name, code_package.language_name, code_location)
            return FissionFunction(func_name)
        elif code_package.is_cached:
            func_name = code_package.cached_config["name"]
            code_location = code_package.code_location
            self.create_env_if_needed(language, self.available_languages_images[language], self.available_languages_builders[language])
            self.update_function(func_name, code_package.language_name, path)

            cached_cfg = code_package.cached_config
            cached_cfg["code_size"] = size
            cached_cfg["timeout"] = timeout
            cached_cfg["memory"] = memory
            cached_cfg["hash"] = code_package.hash
            self.cache_client.update_function(
                self.name(), benchmark.replace('-','.'), code_package.language_name, path, cached_cfg
            )
            code_package.query_cache()
            logging.info(
                "Updating cached function {fname} in {loc}".format(
                    fname=func_name, loc=code_location
                )
            )
            return FissionFunction(func_name)
        else:
            code_location = code_package.benchmark_path
            func_name = "{}-{}-{}".format(benchmark, language, memory)
            self.create_env_if_needed(language, self.available_languages_images[language], self.available_languages_builders[language])
            self.create_function(func_name, language, path)
            self.cache_client.add_function(
                deployment=self.name(),
                benchmark=benchmark.replace('-','.'),
                language=language,
                code_package=path,
                language_config={
                    "name": func_name,
                    "code_size": size,
                    "runtime": language_runtime,
                    "memory": memory,
                    "timeout": timeout,
                    "hash": code_package.hash
                },
                storage_config={
                    "buckets": {
                        "input": self.storage.input_buckets,
                        "output": self.storage.output_buckets
                        }
                },
            )
            code_package.query_cache()
            return FissionFunction(func_name)
