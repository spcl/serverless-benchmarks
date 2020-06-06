import logging
import os
import shutil
import subprocess
import docker
from typing import Dict, Tuple
from sebs.cache import Cache
from sebs.config import SeBSConfig
from sebs.faas.function import Function
from sebs.faas.system import System
from sebs.fission.fissionFunction import FissionFunction
from sebs.benchmark import Benchmark


class Fission(System):
    def __init__(
        self, sebs_config: SeBSConfig, cache_client: Cache, docker_client: docker.client
    ):
        super().__init__(sebs_config, cache_client, docker_client)

    def initialize(self, config: Dict[str, str] = {}):
        subprocess.call(["./fissionBashScripts/run_fission.sh"])

    def package_code(self, benchmark: Benchmark) -> Tuple[str, int]:
        CONFIG_FILES = {
            "python": ["handler.py", "requirements.txt", ".python_packages"],
            "nodejs": ["handler.js", "package.json", "node_modules"],
        }
        directory = benchmark.code_location
        package_config = CONFIG_FILES[benchmark.language_name]
        function_dir = os.path.join(directory, "function")
        os.makedirs(function_dir)
        for file in os.listdir(directory):
            if file not in package_config:
                file = os.path.join(directory, file)
                shutil.move(file, function_dir)
        bytes_size = os.path.getsize(function_dir)
        return function_dir, bytes_size

    def update_function(self, name: str, path: str):
        subprocess.call(["./fissionBashScripts/update_fission_fuction.sh", name, path])

    def create_function(self, name: str, language: str, path: str):
        CONFIG_FILES = {"python": "fission/python-env", "nodejs": "fission/node-env"}

        subprocess.call(
            [
                "./fissionBashScripts/create_fission_function.sh",
                name,
                CONFIG_FILES[language],
                path,
                language,
            ]
        )

    def get_function(self, code_package: Benchmark) -> Function:
        path, size = self.package_code(code_package)

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
        benchmark = code_package.benchmark

        if code_package.is_cached and code_package.is_cached_valid:
            func_name = code_package.cached_config["name"]
            code_location = code_package.code_location
            logging.info(
                "Using cached function {fname} in {loc}".format(
                    fname=func_name, loc=code_location
                )
            )
            return FissionFunction(func_name)
        elif code_package.is_cached:
            func_name = code_package.cached_config["name"]
            code_location = code_package.code_location
            timeout = code_package.benchmark_config.timeout
            memory = code_package.benchmark_config.memory

            self.update_function(func_name, path)

            cached_cfg = code_package.cached_config
            cached_cfg["code_size"] = size
            cached_cfg["timeout"] = timeout
            cached_cfg["memory"] = memory
            cached_cfg["hash"] = code_package.hash
            self.cache_client.update_function(
                self.name(), benchmark, code_package.language_name, path, cached_cfg
            )
            code_package.query_cache()
            logging.info(
                "Updating cached function {fname} in {loc}".format(
                    fname=func_name, loc=code_location
                )
            )
            return FissionFunction(func_name)
        else:
            code_location = code_package.code_location
            language = code_package.language_name
            language_runtime = code_package.language_version
            timeout = code_package.benchmark_config.timeout
            memory = code_package.benchmark_config.memory

            func_name = "{}-{}-{}".format(benchmark, language, memory)

            self.create_function(func_name, language, path)

            self.cache_client.add_function(
                deployment=self.name(),
                benchmark=benchmark,
                language=language,
                code_package=path,
                language_config={
                    "name": func_name,
                    "code_size": size,
                    "runtime": language_runtime,
                    "role": "FissionRole",
                    "memory": memory,
                    "timeout": timeout,
                    "hash": code_package.hash,
                    "url": "WtfUrl",
                },
                storage_config={
                    "buckets": {"input": "input.buckets", "output": "output.buckets"}
                },
            )
            code_package.query_cache()
            return FissionFunction(func_name)
