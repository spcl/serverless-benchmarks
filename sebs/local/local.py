import json
import os
import requests
import shutil
import time
import re
import datetime
from typing import cast, Dict, List, Optional, Type, Tuple, Set  # noqa
import subprocess
import socket

import docker

from sebs.cache import Cache
from sebs.config import SeBSConfig
from sebs.storage.resources import SelfHostedSystemResources
from sebs.utils import LoggingHandlers, is_linux
from sebs.local.config import LocalConfig
from sebs.local.function import LocalFunction
from sebs.local.workflow import LocalWorkflow
from sebs.local.triggers import WorkflowLocalTrigger
from sebs.faas.function import (
    CloudBenchmark,
    Function,
    FunctionConfig,
    ExecutionResult,
    Trigger,
    Workflow,
)
from sebs.faas.system import System
from sebs.faas.config import Resources
from sebs.benchmark import Benchmark
from sebs.faas.fsm import State, Task, Map, Repeat, Loop, Parallel


def _collect_task_names(state: State) -> Set[str]:
    names: Set[str] = set()
    if isinstance(state, Task):
        names.add(state.func_name)
    elif isinstance(state, Repeat):
        names.add(state.func_name)
    elif isinstance(state, Loop):
        names.add(state.func_name)
    elif isinstance(state, Map):
        for nested_name, nested_state in state.funcs.items():
            nested_obj = (
                nested_state
                if isinstance(nested_state, State)
                else State.deserialize(nested_name, nested_state)
            )
            names.update(_collect_task_names(nested_obj))
    elif isinstance(state, Parallel):
        for subworkflow in state.funcs:
            for nested_name, nested_state in subworkflow["states"].items():
                names.update(_collect_task_names(State.deserialize(nested_name, nested_state)))
    return names


def _workflow_task_names(definition: dict) -> Set[str]:
    states = {n: State.deserialize(n, s) for n, s in definition["states"].items()}
    names: Set[str] = set()
    for state in states.values():
        names.update(_collect_task_names(state))
    return names


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

    @staticmethod
    def workflow_type() -> "Type[Workflow]":
        return LocalWorkflow

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
        self._bridge_ip: Optional[str] = self._detect_bridge_ip()

        self.initialize_resources(select_prefix="local")

    @staticmethod
    def _load_workflow_definition(path: str) -> dict:
        with open(path) as definition_file:
            return json.load(definition_file)

    @staticmethod
    def _normalize_workflow_id(name: str) -> str:
        sanitized = re.sub(r"[^A-Za-z0-9_-]", "-", name)
        if not sanitized:
            sanitized = "wf"
        if not sanitized[0].isalpha():
            sanitized = f"wf-{sanitized}"
        return sanitized

    def _allocate_host_port(self, start_port: int, range_size: int = 1000) -> int:
        for port in range(start_port, start_port + range_size):
            if port in self.config.resources.allocated_ports:
                continue
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    sock.bind(("127.0.0.1", port))
                except socket.error:
                    continue
            self.config.resources.allocated_ports.add(port)
            return port
        raise RuntimeError(
            f"Failed to allocate host port for container: No ports available between "
            f"{start_port} and {start_port + range_size - 1}"
        )

    def _detect_bridge_ip(self) -> Optional[str]:
        try:
            network = self._docker_client.networks.get("bridge")
            config = network.attrs.get("IPAM", {}).get("Config", [])
            if config:
                gateway = config[0].get("Gateway")
                if gateway:
                    return gateway
        except docker.errors.DockerException:
            pass
        return None

    def _function_network_endpoint(self, func: LocalFunction) -> Tuple[str, str]:
        host, port = func.url.split(":")
        if is_linux():
            return host, port
        host_override = os.getenv("DOCKER_HOST_IP")
        if host_override:
            return host_override, port
        return host, port

    def _container_service_address(self, endpoint: str) -> str:
        if not endpoint or ":" not in endpoint:
            return endpoint
        host, port = endpoint.split(":", 1)
        if host not in ("127.0.0.1", "localhost"):
            return endpoint
        if self._bridge_ip is None:
            self._bridge_ip = self._detect_bridge_ip()
        if self._bridge_ip:
            return f"{self._bridge_ip}:{port}"
        if is_linux():
            return endpoint
        host_override = os.getenv("DOCKER_HOST_IP", "host.docker.internal")
        return f"{host_override}:{port}"

    def _workflow_env(self, workflow_name: str, module_name: str) -> Dict[str, str]:
        overrides = {
            "SEBS_WORKFLOW_NAME": workflow_name,
            "SEBS_WORKFLOW_FUNC": module_name,
            "SEBS_WORKFLOW_MODULE": f"function.{module_name}",
            "SEBS_WORKFLOW_LOCAL": "1",
        }
        redis_host = self.config.resources.redis_host
        if redis_host:
            if ":" in redis_host:
                host, port = redis_host.split(":", 1)
            else:
                host, port = redis_host, "6379"
            container_host = host
            if host in ("127.0.0.1", "localhost"):
                container_host = self._bridge_ip or host
            overrides["SEBS_REDIS_HOST"] = container_host
            overrides["SEBS_REDIS_PORT"] = port
            if self.config.resources.redis_password:
                overrides["SEBS_REDIS_PASSWORD"] = self.config.resources.redis_password
        return overrides

    def _prepare_workflow_functions(
        self,
        code_package: Benchmark,
        workflow_name: str,
        workflow_id: str,
        definition_path: str,
        definition: dict,
        existing_workflow: Optional[LocalWorkflow] = None,
    ) -> Tuple[List[LocalFunction], Dict[str, Dict[str, str]], str]:

        task_names = sorted(_workflow_task_names(definition))
        if not task_names:
            raise RuntimeError("Workflow definition does not contain any task states.")

        existing_funcs = (
            {func.name: func for func in existing_workflow.functions} if existing_workflow else {}
        )

        functions: List[LocalFunction] = []
        bindings: Dict[str, Dict[str, str]] = {}

        required_containers = {f"{workflow_name}___{task}" for task in task_names}
        obsolete_funcs = set(existing_funcs.keys()) - required_containers
        for obsolete in obsolete_funcs:
            existing_funcs[obsolete].stop()

        for task_name in task_names:
            container_name = f"{workflow_name}___{task_name}"
            existing_func = existing_funcs.get(container_name)
            if existing_func:
                existing_func.stop()

            env = self._workflow_env(workflow_name, task_name)
            func_instance = self._start_container(code_package, container_name, existing_func, env)
            functions.append(func_instance)
            host, port = self._function_network_endpoint(func_instance)
            workflow_function_name = f"{workflow_id}_{task_name}"
            bindings[task_name] = {
                "type": "custom",
                "operation": "rest:post:/",
                "host": host,
                "port": port,
                "workflow_function_name": workflow_function_name,
            }

        resources_dir = os.path.join(code_package.code_location, "workflow_resources")
        workflows_dir = os.path.join(resources_dir, "workflows")
        os.makedirs(workflows_dir, exist_ok=True)
        os.makedirs(resources_dir, exist_ok=True)
        definition_copy = os.path.join(workflows_dir, f"{workflow_id}.sw.json")
        shutil.copy2(definition_path, definition_copy)

        return functions, bindings, definition_copy

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
        code_package: Benchmark,
        directory: str,
        is_workflow: bool,
        is_cached: bool,
    ) -> Tuple[str, int, str]:

        CONFIG_FILES = {
            "python": ["handler.py", "requirements.txt", ".python_packages"],
            "nodejs": ["handler.js", "package.json", "node_modules"],
        }
        package_config = CONFIG_FILES[code_package.language_name]
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
        self,
        code_package: Benchmark,
        func_name: str,
        func: Optional[LocalFunction],
        env_overrides: Optional[Dict[str, str]] = None,
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
        storage_cfg = self.config.resources.storage_config
        if storage_cfg:
            storage_envs = dict(storage_cfg.envs())
            if "MINIO_ADDRESS" in storage_envs:
                storage_envs["MINIO_ADDRESS"] = self._container_service_address(
                    storage_envs["MINIO_ADDRESS"]
                )
            environment = {**storage_envs, **environment}

        if code_package.uses_nosql:

            nosql_storage = self.system_resources.get_nosql_storage()
            nosql_envs = dict(nosql_storage.envs())
            if "NOSQL_STORAGE_ENDPOINT" in nosql_envs:
                nosql_envs["NOSQL_STORAGE_ENDPOINT"] = self._container_service_address(
                    nosql_envs["NOSQL_STORAGE_ENDPOINT"]
                )
            environment = {**environment, **nosql_envs}

            for original_name, actual_name in nosql_storage.get_tables(
                code_package.benchmark
            ).items():
                environment[f"NOSQL_STORAGE_TABLE_{original_name}"] = actual_name

        if env_overrides:
            environment.update(env_overrides)

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
        if not is_linux():
            port = self._allocate_host_port(self.DEFAULT_PORT)
            container_kwargs["command"] = f"/bin/bash /sebs/run_server.sh {port}"
            container_kwargs["ports"] = {f"{port}/tcp": port}
        else:
            port = self.DEFAULT_PORT

        from docker.types import DeviceRequest

        container = self._docker_client.containers.run(
            **container_kwargs,
            device_requests=[DeviceRequest(driver="nvidia", count=-1, capabilities=[["gpu"]])],
        )

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
            func.refresh_endpoint(port)

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

    def create_function_trigger(self, func: Function, trigger_type: Trigger.TriggerType) -> Trigger:
        from sebs.local.function import HTTPTrigger

        function = cast(LocalFunction, func)
        if trigger_type == Trigger.TriggerType.HTTP:
            trigger = HTTPTrigger(function._url)
            trigger.logging_handlers = self.logging_handlers
        else:
            raise RuntimeError("Not supported!")

        function.add_trigger(trigger)
        self.cache_client.update_benchmark(function)
        return trigger

    def cached_benchmark(self, function: CloudBenchmark):
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

    def create_workflow(self, code_package: Benchmark, workflow_name: str) -> Workflow:
        workflow_name = self.format_function_name(workflow_name)
        definition_path = os.path.join(code_package.benchmark_path, "definition.json")
        if not os.path.exists(definition_path):
            raise ValueError(f"No workflow definition found for {workflow_name}")

        definition = self._load_workflow_definition(definition_path)
        workflow_id = self._normalize_workflow_id(workflow_name)

        functions, bindings, definition_output = self._prepare_workflow_functions(
            code_package, workflow_name, workflow_id, definition_path, definition
        )

        function_cfg = FunctionConfig.from_benchmark(code_package)
        workflow = LocalWorkflow(
            workflow_name,
            functions,
            code_package.benchmark,
            workflow_id,
            code_package.hash,
            function_cfg,
            definition_output,
            bindings,
        )
        trigger = WorkflowLocalTrigger(definition_output, bindings)
        trigger.logging_handlers = self.logging_handlers
        workflow.add_trigger(trigger)
        return workflow

    def create_workflow_trigger(
        self, workflow: Workflow, trigger_type: Trigger.TriggerType
    ) -> Trigger:
        workflow = cast(LocalWorkflow, workflow)
        if trigger_type != Trigger.TriggerType.HTTP:
            raise RuntimeError("Local workflows currently support only HTTP triggers.")

        trigger = WorkflowLocalTrigger(workflow.definition_path, workflow.function_bindings)
        trigger.logging_handlers = self.logging_handlers
        workflow.add_trigger(trigger)
        self.cache_client.update_benchmark(workflow)
        return trigger

    def update_workflow(self, workflow: Workflow, code_package: Benchmark):
        workflow = cast(LocalWorkflow, workflow)
        definition_path = os.path.join(code_package.benchmark_path, "definition.json")
        if not os.path.exists(definition_path):
            raise ValueError(f"No workflow definition found for {workflow.name}")

        definition = self._load_workflow_definition(definition_path)
        workflow_id = (
            workflow.workflow_id
            if workflow.workflow_id
            else self._normalize_workflow_id(workflow.name)
        )
        functions, bindings, definition_output = self._prepare_workflow_functions(
            code_package,
            workflow.name,
            workflow_id,
            definition_path,
            definition,
            workflow,
        )
        workflow.set_functions(functions)
        workflow.definition_path = definition_output
        workflow.function_bindings = bindings
        workflow.workflow_id = workflow_id

        triggers = workflow.triggers(Trigger.TriggerType.HTTP)
        if not triggers:
            trigger = WorkflowLocalTrigger(workflow.definition_path, workflow.function_bindings)
            trigger.logging_handlers = self.logging_handlers
            workflow.add_trigger(trigger)
        else:
            for trigger in triggers:
                if isinstance(trigger, WorkflowLocalTrigger):
                    trigger.update(workflow.definition_path, workflow.function_bindings)

        self.logging.info(f"Updated workflow {workflow.name} definition.")

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
