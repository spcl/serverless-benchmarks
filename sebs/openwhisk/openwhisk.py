import subprocess
import logging
import shutil
import json
import os
from typing import Tuple

import sebs.benchmark
from sebs.faas import System, PersistentStorage
from sebs.faas.config import Config
from sebs.faas.function import Function
from .config import OpenWhiskConfig



class OpenWhisk(System):
    _config: OpenWhiskConfig

    @property
    def config(self) -> Config:
        return self._config

    def get_storage(self, replace_existing: bool) -> PersistentStorage:
        pass

    def get_function(self, code_package: sebs.benchmark.Benchmark) -> Function:
        pass

    def shutdown(self) -> None:
        pass

    @staticmethod
    def __run_check_process__(cmd: str) -> None:
        subprocess.run(
            cmd.split(),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @staticmethod
    def __check_installation__(app: str, cmd: str) -> None:
        try:
            logging.info('Checking {} installation...'.format(app))
            OpenWhisk.__run_check_process__(cmd)
            logging.info('Check successful, proceeding...')
        except subprocess.CalledProcessError:
            logging.error('Cannot find {}, aborting'.format(app))
            exit(1)

    @staticmethod
    def install_kind() -> None:
        try:
            logging.info('Installing kind...')
            OpenWhisk.__run_check_process__('GO111MODULE="on" go get sigs.k8s.io/kind@v0.8.1')
            logging.info('Kind has been installed')
        except subprocess.CalledProcessError as e:
            logging.error('Cannot install kind, reason: {}'.format(e.output))
            exit(1)

    @staticmethod
    def check_kind_installation() -> None:
        try:
            OpenWhisk.__run_check_process__('kind --version')
        except subprocess.CalledProcessError:
            logging.error('Cannot find kind executable, installing...')
            OpenWhisk.install_kind()

    @staticmethod
    def check_kubectl_installation() -> None:
        OpenWhisk.__check_installation__("kubectl", "kubectl version")

    @staticmethod
    def check_helm_installation() -> None:
        OpenWhisk.__check_installation__("helm", "helm version")

    @staticmethod
    def check_openwhisk_installation(namespace: str) -> None:
        try:
            logging.info('Checking openwhisk installation.')
            namespaces = subprocess.run(
                "kubectl get namespaces".split(),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                ["grep", namespace],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                input=namespaces.stdout,
            )
            logging.info("Openwhisk installed!")
        except subprocess.CalledProcessError:
            logging.info("Openwhisk is not installed, proceeding with installation...")
            subprocess.run(
                "helm install owdev "
            )

    @staticmethod
    def name() -> str:
        return "openwhisk"

    def package_code(self, benchmark: sebs.Benchmark) -> Tuple[str, int]:

        benchmark.build()
        node = 'nodejs'
        node_handler = 'handler.js'
        CONFIG_FILES = {
            'python': ['virtualenv', '__main__.py'],
            node: [node_handler, 'package.json', 'node_modules']
        }
        directory = benchmark.code_location
        package_config = CONFIG_FILES[benchmark.language_name]
        function_dir = os.path.join(directory, "function")
        os.makedirs(function_dir)

        # openwhisk needs main function to be named ina packaged.json
        if benchmark.language_name == node:
            filename = 'package.json'
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
        os.chdir(directory)
        subprocess.run(
            "zip -r {}.zip ./".format(benchmark.benchmark).split(),
            stdout=subprocess.DEVNULL,
        )
        benchmark_archive = "{}.zip".format(
            os.path.join(directory, benchmark.benchmark)
        )
        logging.info("Created {} archive".format(benchmark_archive))
        bytes_size = os.path.getsize(benchmark_archive)
        return benchmark_archive, bytes_size
