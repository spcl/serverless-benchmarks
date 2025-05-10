import os
import requests
import shutil
import time
from typing import cast, Dict, List, Optional, Type, Tuple  # noqa
import subprocess
import socket

import docker

from sebs.cache import Cache
from sebs.config import SeBSConfig
from sebs.storage.resources import SelfHostedSystemResources
from sebs.utils import LoggingHandlers, is_linux
from sebs.local.config import LocalConfig
from sebs.local.function import LocalFunction
from sebs.faas.function import Function, FunctionConfig, ExecutionResult, Trigger
from sebs.faas.system import System
from sebs.faas.config import Resources
from sebs.benchmark import Benchmark


class Local(System):

    DEFAULT_PORT = 9000

    @staticmethod
    def name():
        return "local"

    @staticmethod
    def typename():
        return "Local"

    @staticmethod
    def function_type() -> "Type[Function]":
        return LocalFunction

    @property
    def config(self) -> LocalConfig:
        return self._config

    @property
    def remove_containers(self) -> bool:
        return self._remove_containers

    @remove_containers.setter
    def remove_containers(self, val: bool):
        self._remove_containers = val

    @property
    def measure_interval(self) -> int:
        return self._measure_interval

    @property
    def measurements_enabled(self) -> bool:
        return self._measure_interval > -1

    @property
    def measurement_path(self) -> Optional[str]:
        return self._memory_measurement_path

    def __init__(
        self,
        sebs_config: SeBSConfig,
        config: LocalConfig,
        cache_client: Cache,
        docker_client: docker.client,
        logger_handlers: LoggingHandlers,
    ):
        super().__init__(
            sebs_config,
            cache_client,
            docker_client,
            SelfHostedSystemResources(
                "local", config, cache_client, docker_client, logger_handlers
            ),
        )
        self.logging_handlers = logger_handlers
        self._config = config
        self._remove_containers = True
        self._memory_measurement_path: Optional[str] = None
        # disable external measurements
        self._measure_interval = -1

        self.initialize_resources(select_prefix="local")

    """
        Shut down minio storage instance.
    """

    def shutdown(self):
        super().shutdown()

    """
        It would be sufficient to just pack the code and ship it as zip to AWS.
        However, to have a compatible function implementation across providers,
        we create a small module.
        Issue: relative imports in Python when using storage wrapper.
        Azure expects a relative import inside a module.

        Structure:
        function
        - function.py
        - storage.py
        - resources
        handler.py

        dir: directory where code is located
        benchmark: benchmark name
    """

    def package_code(
        self,
        directory: str,
        language_name: str,
        language_version: str,
        architecture: str,
        benchmark: str,
        is_cached: bool,
        container_deployment: bool,
    ) -> Tuple[str, int, str]:

        CONFIG_FILES = {
            "python": ["handler.py", "requirements.txt", ".python_packages"],
            "nodejs": ["handler.js", "package.json", "node_modules"],
        }
        package_config = CONFIG_FILES[language_name]
        function_dir = os.path.join(directory, "function")
        os.makedirs(function_dir)
        # move all files to 'function' except handler.py
        for file in os.listdir(directory):
            if file not in package_config:
                file = os.path.join(directory, file)
                shutil.move(file, function_dir)

        bytes_size = os.path.getsize(directory)
        mbytes = bytes_size / 1024.0 / 1024.0
        self.logging.info("Function size {:2f} MB".format(mbytes))

        return directory, bytes_size, ""

    def _start_container(
        self, code_package: Benchmark, func_name: str, func: Optional[LocalFunction]
    ) -> LocalFunction:

        container_name = "{}:run.local.{}.{}".format(
            self._system_config.docker_repository(),
            code_package.language_name,
            code_package.language_version,
        )

        environment = {
            "CONTAINER_UID": str(os.getuid()),
            "CONTAINER_GID": str(os.getgid()),
            "CONTAINER_USER": self._system_config.username(self.name(), code_package.language_name),
        }
        if self.config.resources.storage_config:

            environment = {**self.config.resources.storage_config.envs(), **environment}

        if code_package.uses_nosql:

            nosql_storage = self.system_resources.get_nosql_storage()
            environment = {**environment, **nosql_storage.envs()}

            for original_name, actual_name in nosql_storage.get_tables(
                code_package.benchmark
            ).items():
                environment[f"NOSQL_STORAGE_TABLE_{original_name}"] = actual_name

        # FIXME: make CPUs configurable
        # FIXME: configure memory
        # FIXME: configure timeout
        # cpuset_cpus=cpuset,
        # required to access perf counters
        # alternative: use custom seccomp profile
        container_kwargs = {
            "image": container_name,
            "command": f"/bin/bash /sebs/run_server.sh {self.DEFAULT_PORT}",
            "volumes": {code_package.code_location: {"bind": "/function", "mode": "ro"}},
            "environment": environment,
            "privileged": True,
            "security_opt": ["seccomp:unconfined"],
            "network_mode": "bridge",
            "remove": self.remove_containers,
            "stdout": True,
            "stderr": True,
            "detach": True,
            # "tty": True,
        }

        # If SeBS is running on non-linux platforms,
        # container port must be mapped to host port to make it reachable
        # Check if the system is NOT Linux or that it is WSL
        port = self.DEFAULT_PORT
        if not is_linux():
            port_found = False
            for p in range(self.DEFAULT_PORT, self.DEFAULT_PORT + 1000):
                # check no container has been deployed on docker's port p
                if p not in self.config.resources.allocated_ports:
                    # check if port p on the host is free
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                        try:
                            s.bind(("127.0.0.1", p))
                            # The port is available
                            port = p
                            port_found = True
                            self.config.resources.allocated_ports.add(p)
                            break
                        except socket.error:
                            # The port is already in use
                            continue

            if not port_found:
                raise RuntimeError(
                    f"Failed to allocate port for container: No ports available between "
                    f"{self.DEFAULT_PORT} and {self.DEFAULT_PORT + 999}"
                )

            container_kwargs["command"] = f"/bin/bash /sebs/run_server.sh {port}"
            container_kwargs["ports"] = {f"{port}/tcp": port}

        container = self._docker_client.containers.run(**container_kwargs)

        pid: Optional[int] = None
        if self.measurements_enabled and self._memory_measurement_path is not None:
            # launch subprocess to measure memory
            proc = subprocess.Popen(
                [
                    "python3",
                    "./sebs/local/measureMem.py",
                    "--container-id",
                    container.id,
                    "--measure-interval",
                    str(self._measure_interval),
                    "--measurement-file",
                    self._memory_measurement_path,
                ]
            )
            pid = proc.pid

        if func is None:
            function_cfg = FunctionConfig.from_benchmark(code_package)
            func = LocalFunction(
                container,
                port,
                func_name,
                code_package.benchmark,
                code_package.hash,
                function_cfg,
                pid,
            )
        else:
            func.container = container
            func._measurement_pid = pid

        # Wait until server starts
        max_attempts = 10
        attempts = 0
        while attempts < max_attempts:
            try:
                requests.get(f"http://{func.url}/alive")
                break
            except requests.exceptions.ConnectionError:
                time.sleep(0.25)
                attempts += 1

        if attempts == max_attempts:
            raise RuntimeError(
                f"Couldn't start {func_name} function at container "
                f"{container.id} , running on {func.url}"
            )

        self.logging.info(
            f"Started {func_name} function at container {container.id} , running on {func._url}"
        )

        return func

    def create_function(
        self,
        code_package: Benchmark,
        func_name: str,
        container_deployment: bool,
        container_uri: str,
    ) -> "LocalFunction":

        if container_deployment:
            raise NotImplementedError("Container deployment is not supported in Local")
        return self._start_container(code_package, func_name, None)

    """
        Restart Docker container
    """

    def update_function(
        self,
        function: Function,
        code_package: Benchmark,
        container_deployment: bool,
        container_uri: str,
    ):
        func = cast(LocalFunction, function)
        func.stop()
        self.logging.info("Allocating a new function container with updated code")
        self._start_container(code_package, function.name, func)

    """
        For local functions, we don't need to do anything for a cached function.
        There's only one trigger - HTTP.
    """

    def create_trigger(self, func: Function, trigger_type: Trigger.TriggerType) -> Trigger:
        from sebs.local.function import HTTPTrigger

        function = cast(LocalFunction, func)
        if trigger_type == Trigger.TriggerType.HTTP:
            trigger = HTTPTrigger(function._url)
            trigger.logging_handlers = self.logging_handlers
        else:
            raise RuntimeError("Not supported!")

        function.add_trigger(trigger)
        self.cache_client.update_function(function)
        return trigger

    def cached_function(self, function: Function):
        pass

    def update_function_configuration(self, function: Function, code_package: Benchmark):
        self.logging.error("Updating function configuration of local deployment is not supported")
        raise RuntimeError("Updating function configuration of local deployment is not supported")

    def download_metrics(
        self,
        function_name: str,
        start_time: int,
        end_time: int,
        requests: Dict[str, ExecutionResult],
        metrics: dict,
    ):
        pass

    def enforce_cold_start(self, functions: List[Function], code_package: Benchmark):
        raise NotImplementedError()

    @staticmethod
    def default_function_name(
        code_package: Benchmark, resources: Optional[Resources] = None
    ) -> str:
        # Create function name
        if resources is not None:
            func_name = "sebs-{}-{}-{}-{}".format(
                resources.resources_id,
                code_package.benchmark,
                code_package.language_name,
                code_package.language_version,
            )
        else:
            func_name = "sebd-{}-{}-{}".format(
                code_package.benchmark,
                code_package.language_name,
                code_package.language_version,
            )
        return func_name

    @staticmethod
    def format_function_name(func_name: str) -> str:
        return func_name

    def start_measurements(self, measure_interval: int) -> Optional[str]:

        self._measure_interval = measure_interval

        if not self.measurements_enabled:
            return None

        # initialize an empty file for measurements to be written to
        import tempfile
        from pathlib import Path

        fd, self._memory_measurement_path = tempfile.mkstemp()
        Path(self._memory_measurement_path).touch()
        os.close(fd)

        return self._memory_measurement_path
