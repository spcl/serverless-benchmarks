import base64
import datetime
import json
import logging
import os
import shutil
import time
import subprocess
import docker
import uuid
from typing import Dict, List, Optional, Tuple, Union, cast

from sebs import utils
from sebs.benchmark import Benchmark
from sebs.cache import Cache
from sebs.config import SeBSConfig
from sebs.faas.function import Function
from sebs.faas.storage import PersistentStorage
from sebs.faas.system import System
from sebs.fission.fissionFunction import FissionFunction
from sebs.benchmark import Benchmark


class Fission(System):
    def __init__(
        self,
        sebs_config: SeBSConfig,
        cache_client: Cache,
        docker_client: docker.client,
    ):
        super().__init__(sebs_config, cache_client, docker_client)

    def initialize(self, config: Dict[str, str] = {}):
        subprocess.call(["./run_fission.sh"])

    def package_code(self, benchmark: Benchmark) -> Tuple[str, int]:
        CONFIG_FILES = {
            "python": ["handler.py", "requirements.txt", ".python_packages"],
            "nodejs": ["handler.js", "package.json", "node_modules"],
        }
        package_config = CONFIG_FILES[benchmark.language]
        function_dir = os.path.join(dir, "function")
        os.makedirs(function_dir)
        for file in os.listdir(dir):
            if file not in package_config:
                file = os.path.join(dir, file)
                shutil.move(file, function_dir)
        bytes_size = os.path.getsize(function_dir)
        return function_dir, bytes_size

    def update_function(self, name: str, path: str):
        subprocess.call(["./update_fission_fuction.sh", name, path])

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
            return FissionFunction(self)
        elif code_package.is_cached:
            func_name = code_package.cached_config["name"]
            code_location = code_package.code_location
            timeout = code_package.benchmark_config.timeout
            memory = code_package.benchmark_config.memory
            language = code_package.language

            self.update_function(func_name, path)

            cached_cfg = code_package.cached_config
            cached_cfg["code_size"] = size
            cached_cfg["timeout"] = timeout
            cached_cfg["memory"] = memory
            cached_cfg["hash"] = code_package.hash
            self.cache_client.update_function(
                self.name(), benchmark, code_package.language_name, path, cached_cfg
            )
            # FIXME: fix after dissociating code package and benchmark
            code_package.query_cache()

            logging.info(
                "Updating cached function {fname} in {loc}".format(
                    fname=func_name, loc=code_location
                )
            )

            return FissionFunction(self)
            # no cached instance, create package and upload code
        else:

            code_location = code_package.code_location
            language = code_package.language_name
            language_runtime = code_package.language_version
            timeout = code_package.benchmark_config.timeout
            memory = code_package.benchmark_config.memory

            func_name = "{}-{}-{}".format(benchmark, language, memory)

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
                    "url": "WtfUrl"
                }
            )
            # FIXME: fix after dissociating code package and benchmark
            code_package.query_cache()
            return FissionFunction(self)
