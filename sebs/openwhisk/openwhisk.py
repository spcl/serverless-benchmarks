import json
import logging
import os
import shutil
import subprocess
from typing import Tuple

import docker

from sebs.benchmark import Benchmark
from sebs.cache import Cache
from sebs.faas import System, PersistentStorage
from sebs.faas.function import Function
from sebs.openwhisk.minio import Minio
from .config import OpenWhiskConfig
from .function import OpenwhiskFunction
from ..config import SeBSConfig


class OpenWhisk(System):
    _config: OpenWhiskConfig
    storage: Minio

    def __init__(self, system_config: SeBSConfig, config: OpenWhiskConfig, cache_client: Cache,
                 docker_client: docker.client):
        super().__init__(system_config, cache_client, docker_client)
        self._config = config

    @property
    def config(self) -> OpenWhiskConfig:
        return self._config

    def get_storage(self, replace_existing: bool = False) -> PersistentStorage:
        self.storage = Minio(self.docker_client)
        return self.storage

    def shutdown(self) -> None:
        if self.config.shutdownStorage:
            self.storage.storage_container.kill()
        if self.config.removeCluster:
            from tools.openwhisk_preparation import delete_cluster
            delete_cluster()

    @staticmethod
    def name() -> str:
        return "openwhisk"

    def package_code(self, benchmark: Benchmark) -> Tuple[str, int]:
        benchmark.build()
        node = 'nodejs'
        node_handler = 'index.js'
        CONFIG_FILES = {
            'python': ['virtualenv', '__main__.py', 'requirements.txt'],
            node: [node_handler, 'package.json', 'node_modules']
        }
        directory = benchmark.code_location
        package_config = CONFIG_FILES[benchmark.language_name]
        function_dir = os.path.join(directory, "function")
        os.makedirs(function_dir)

        with open('./code/minioConfig.json', 'w+') as minio_config:
            minio_config_json = {
                'access_key': self.storage.access_key,
                'secret_key': self.storage.secret_key,
                'url': self.storage.url,
            }
            minio_config.write(json.dumps(minio_config_json))

        # openwhisk needs main function to be named in a package.json

        if benchmark.language_name == node:
            filename = 'code/package.json'
            with open(filename, 'r') as f:
                data = json.load(f)
                data['main'] = node_handler

            os.remove(filename)
            with open(filename, 'w') as f:
                json.dump(data, f, indent=4)

        for file in os.listdir(directory):
            if file not in package_config:
                file = os.path.join(directory, file)
                shutil.move(file, function_dir)
        builder_image = self.system_config.benchmark_base_images(self.name(), benchmark.language_name)[
            benchmark.language_version
        ]
        if benchmark.language_name == node:
            build_command = 'npm install'
            volumes = {
                directory: {'bind': '/nodejsAction'}
            }
        else:
            build_command = 'cd /tmp && virtualenv virtualenv && source virtualenv/bin/activate && ' \
                            'pip install -r requirements.txt'
            volumes = {
                directory: {'bind': '/tmp'}
            }

        command = '-c "{}"'.format(build_command)

        self.docker_client.containers.run(
            builder_image,
            entrypoint="bash",
            command=command,
            volumes=volumes,
            remove=True,
            stdout=True,
            stderr=True,
            user='1000:1000',
            network_mode="bridge",
            privileged=True,
            tty=True
        )
        os.chdir(directory)
        subprocess.run(
            "zip -r {}.zip ./".format(benchmark.benchmark).split(),
            stdout=subprocess.DEVNULL,
        )
        benchmark_archive = "{}.zip".format(
            os.path.join(directory, benchmark.benchmark)
        )
        logging.info(f"Created {benchmark_archive} archive")
        bytes_size = os.path.getsize(benchmark_archive)
        return benchmark_archive, bytes_size

    def create_function(self, benchmark: Benchmark, function_name: str, zip_path: str) -> None:
        logging.info("Creating action on openwhisk")
        try:
            actions = subprocess.run(
                "wsk -i action list".split(),
                stderr=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
            )
            subprocess.run(
                f"grep {function_name}".split(),
                stderr=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                input=actions.stdout,
                check=True,
            )
            logging.info(f"Function {function_name} already exist")

        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logging.error(f"ERROR: {e}")
            try:
                language_version = benchmark.language_version
                if benchmark.language_name == "python":
                    language_version = language_version[0]
                subprocess.run(
                    f"wsk -i action create {function_name} --kind {benchmark.language_name}:{language_version} "
                    f"{zip_path}".split(),
                    stderr=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    check=True,
                )
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                logging.error(f"Cannot create action {function_name}, reason: {e}")
                exit(1)

    def get_function(self, code_package: Benchmark) -> Function:
        if (
                code_package.language_version
                not in self.system_config.supported_language_versions(self.name(), code_package.language_name)
        ):
            raise Exception(
                "Unsupported {language} version {version} in Openwhisk!".format(
                    language=code_package.language_name,
                    version=code_package.language_version,
                )
            )
        benchmark = code_package.benchmark
        code_location = code_package.code_location

        if code_package.is_cached and code_package.is_cached_valid:
            func_name = code_package.cached_config["name"]
            logging.info(
                "Using cached function {fname} in {loc}".format(
                    fname=func_name, loc=code_location
                )
            )
            return OpenwhiskFunction(func_name)
        elif code_package.is_cached:
            func_name = code_package.cached_config["name"]
            timeout = code_package.benchmark_config.timeout
            memory = code_package.benchmark_config.memory

            # Run Openwhisk-specific part of building code.
            package, code_size = self.package_code(code_package)

            self.create_function(
                code_package, func_name, package,
            )

            cached_cfg = code_package.cached_config
            cached_cfg["code_size"] = code_size
            cached_cfg["timeout"] = timeout
            cached_cfg["memory"] = memory
            cached_cfg["hash"] = code_package.hash
            self.cache_client.update_function(
                self.name(), benchmark, code_package.language_name, package, cached_cfg
            )
            # FIXME: fix after dissociating code package and benchmark
            code_package.query_cache()

            logging.info(
                "Updating cached function {fname} in {loc}".format(
                    fname=func_name, loc=code_location
                )
            )

            return OpenwhiskFunction(func_name)
        # no cached instance, create package and upload code
        else:

            language = code_package.language_name
            language_runtime = code_package.language_version
            timeout = code_package.benchmark_config.timeout
            memory = code_package.benchmark_config.memory

            # Create function name, validation regexp if needed: \A([\w]|[\w][\w@ .-]*[\w@.-]+)\z
            func_name = "{}-{}-{}".format(benchmark, language, memory)

            package, code_size = self.package_code(code_package)
            # todo: check if function exists, if so delte otherwise create

            self.cache_client.add_function(
                deployment=self.name(),
                benchmark=benchmark,
                language=language,
                code_package=package,
                language_config={
                    "name": func_name,
                    "code_size": code_size,
                    "runtime": language_runtime,
                    "memory": memory,
                    "timeout": timeout,
                    "hash": code_package.hash,
                },
                storage_config={
                    "buckets": {
                        "input": self.storage.input_buckets,
                        "output": self.storage.output_buckets,
                    }
                },
            )

            self.create_function(code_package, func_name, package)

            # FIXME: fix after dissociating code package and benchmark
            code_package.query_cache()
            return OpenwhiskFunction(func_name)
