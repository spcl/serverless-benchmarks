import os
import shutil
from typing import cast, Dict, List, Optional, Tuple, Set, Type

import docker

from sebs.cache import Cache
from sebs.config import SeBSConfig
from sebs.storage.resources import SelfHostedSystemResources
from sebs.utils import LoggingHandlers
from sebs.sonataflow.config import SonataFlowConfig
from sebs.sonataflow.workflow import SonataFlowWorkflow
from sebs.sonataflow.triggers import WorkflowSonataFlowTrigger
from sebs.sonataflow.generator import SonataFlowGenerator
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
from sebs.local.function import LocalFunction
from sebs.local.local import Local


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


class SonataFlow(Local):
    DEFAULT_PORT = 9000

    @staticmethod
    def name():
        return "sonataflow"

    @staticmethod
    def typename():
        return "SonataFlow"

    @staticmethod
    def function_type() -> "Type[Function]":
        return LocalFunction

    @staticmethod
    def workflow_type() -> "Type[Workflow]":
        return SonataFlowWorkflow

    @property
    def config(self) -> SonataFlowConfig:
        return self._config

    def __init__(
        self,
        sebs_config: SeBSConfig,
        config: SonataFlowConfig,
        cache_client: Cache,
        docker_client: docker.client,
        logger_handlers: LoggingHandlers,
    ):
        System.__init__(
            self,
            sebs_config,
            cache_client,
            docker_client,
            SelfHostedSystemResources(
                "sonataflow", config, cache_client, docker_client, logger_handlers
            ),
        )
        self.logging_handlers = logger_handlers
        self._config = config
        self._remove_containers = True
        self._memory_measurement_path: Optional[str] = None
        self._measure_interval = -1
        self._bridge_ip: Optional[str] = self._detect_bridge_ip()
        self.initialize_resources(select_prefix="sonataflow")

    # Reuse networking helpers from Local
    def _detect_bridge_ip(self) -> Optional[str]:
        return Local._detect_bridge_ip(self)

    def _container_service_address(self, endpoint: str) -> str:
        return Local._container_service_address(self, endpoint)

    def _function_network_endpoint(self, func: LocalFunction) -> Tuple[str, str]:
        return Local._function_network_endpoint(self, func)

    def _workflow_env(self, workflow_name: str, module_name: str) -> Dict[str, str]:
        return Local._workflow_env(self, workflow_name, module_name)

    def _allocate_host_port(self, start_port: int, range_size: int = 1000) -> int:
        return Local._allocate_host_port(self, start_port, range_size)

    @staticmethod
    def _normalize_workflow_id_for_sonataflow(name: str) -> str:
        """
        Normalize workflow ID for SonataFlow.
        SonataFlow generates Java classes from workflow IDs, so they must be valid Java identifiers.
        Replace hyphens with underscores and ensure it starts with a letter.
        """
        import re
        # Replace any non-alphanumeric characters (except underscore) with underscore
        sanitized = re.sub(r"[^A-Za-z0-9_]", "_", name)
        if not sanitized:
            sanitized = "wf"
        # Ensure it starts with a letter
        if not sanitized[0].isalpha():
            sanitized = f"wf_{sanitized}"
        return sanitized

    def _start_container(
        self,
        code_package: Benchmark,
        func_name: str,
        func: Optional[LocalFunction],
        env_overrides: Optional[Dict[str, str]] = None,
    ) -> LocalFunction:
        # Override to use custom network for SonataFlow
        # Create sebs-network if it doesn't exist
        try:
            self._docker_client.networks.get("sebs-network")
        except docker.errors.NotFound:
            self._docker_client.networks.create("sebs-network", driver="bridge")

        # Call parent method to start the container
        func_instance = Local._start_container(self, code_package, func_name, func, env_overrides)

        # Connect the container to sebs-network
        try:
            network = self._docker_client.networks.get("sebs-network")
            network.connect(func_instance.container.id)
            self.logging.info(f"Connected container {func_instance.container.name} to sebs-network")
        except Exception as e:
            self.logging.warning(f"Failed to connect container to sebs-network: {e}")

        return func_instance

    def _load_workflow_definition(self, path: str) -> dict:
        return Local._load_workflow_definition(path)

    def _prepare_workflow_functions(
        self,
        code_package: Benchmark,
        workflow_name: str,
        workflow_id: str,
        definition_path: str,
        definition: dict,
        existing_workflow: Optional[SonataFlowWorkflow] = None,
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
        definition_copy = os.path.join(workflows_dir, f"{workflow_id}.json")
        shutil.copy2(definition_path, definition_copy)

        return functions, bindings, definition_copy

    def create_workflow(self, code_package: Benchmark, workflow_name: str) -> Workflow:
        workflow_name = self.format_function_name(workflow_name)
        definition_path = os.path.join(code_package.benchmark_path, "definition.json")
        if not os.path.exists(definition_path):
            raise ValueError(f"No workflow definition found for {workflow_name}")

        definition = self._load_workflow_definition(definition_path)
        workflow_id = self._normalize_workflow_id_for_sonataflow(workflow_name)

        functions, bindings, definition_copy = self._prepare_workflow_functions(
            code_package, workflow_name, workflow_id, definition_path, definition
        )

        generator = SonataFlowGenerator(workflow_id, bindings)
        generator.parse(definition_path)
        sonataflow_definition = generator.generate()

        sf_dir = os.path.join(code_package.code_location, "workflow_resources", "sonataflow")
        os.makedirs(sf_dir, exist_ok=True)
        sonataflow_path = os.path.join(sf_dir, f"{workflow_id}.sw.json")
        with open(sonataflow_path, "w") as outf:
            outf.write(sonataflow_definition)

        function_cfg = FunctionConfig.from_benchmark(code_package)
        workflow = SonataFlowWorkflow(
            workflow_name,
            functions,
            code_package.benchmark,
            workflow_id,
            code_package.hash,
            function_cfg,
            sonataflow_path,
            bindings,
        )
        trigger = WorkflowSonataFlowTrigger(
            workflow.workflow_id,
            self.config.resources.runtime_url,
            self.config.resources.endpoint_prefix,
        )
        trigger.logging_handlers = self.logging_handlers
        workflow.add_trigger(trigger)
        return workflow

    def create_workflow_trigger(
        self, workflow: Workflow, trigger_type: Trigger.TriggerType
    ) -> Trigger:
        workflow = cast(SonataFlowWorkflow, workflow)
        if trigger_type != Trigger.TriggerType.HTTP:
            raise RuntimeError("SonataFlow workflows currently support only HTTP triggers.")

        trigger = WorkflowSonataFlowTrigger(
            workflow.workflow_id,
            self.config.resources.runtime_url,
            self.config.resources.endpoint_prefix,
        )
        trigger.logging_handlers = self.logging_handlers
        workflow.add_trigger(trigger)
        self.cache_client.update_benchmark(workflow)
        return trigger

    def update_workflow(self, workflow: Workflow, code_package: Benchmark):
        workflow = cast(SonataFlowWorkflow, workflow)
        definition_path = os.path.join(code_package.benchmark_path, "definition.json")
        if not os.path.exists(definition_path):
            raise ValueError(f"No workflow definition found for {workflow.name}")

        definition = self._load_workflow_definition(definition_path)
        workflow_id = workflow.workflow_id if workflow.workflow_id else self._normalize_workflow_id_for_sonataflow(workflow.name)
        functions, bindings, _ = self._prepare_workflow_functions(
            code_package,
            workflow.name,
            workflow_id,
            definition_path,
            definition,
            workflow,
        )

        generator = SonataFlowGenerator(workflow_id, bindings)
        generator.parse(definition_path)
        sonataflow_definition = generator.generate()
        sonataflow_path = os.path.join(
            code_package.code_location, "workflow_resources", "sonataflow", f"{workflow_id}.sw.json"
        )
        os.makedirs(os.path.dirname(sonataflow_path), exist_ok=True)
        with open(sonataflow_path, "w") as outf:
            outf.write(sonataflow_definition)

        workflow.set_functions(functions)
        workflow.definition_path = sonataflow_path
        workflow.function_bindings = bindings
        workflow.workflow_id = workflow_id

        triggers = workflow.triggers(Trigger.TriggerType.HTTP)
        if not triggers:
            trigger = WorkflowSonataFlowTrigger(
                workflow.workflow_id,
                self.config.resources.runtime_url,
                self.config.resources.endpoint_prefix,
            )
            trigger.logging_handlers = self.logging_handlers
            workflow.add_trigger(trigger)
        else:
            for trigger in triggers:
                if isinstance(trigger, WorkflowSonataFlowTrigger):
                    trigger.update(self.config.resources.runtime_url, self.config.resources.endpoint_prefix)

        self.logging.info(f"Updated SonataFlow workflow {workflow.name} definition.")

    def initialize(self, config: Dict[str, str] = {}, resource_prefix: Optional[str] = None):
        self.initialize_resources(select_prefix=resource_prefix or "sonataflow")

    def package_code(
        self,
        code_package: Benchmark,
        directory: str,
        is_workflow: bool,
        is_cached: bool,
    ) -> Tuple[str, int, str]:
        return Local.package_code(self, code_package, directory, is_workflow, is_cached)

    def create_function(
        self,
        code_package: Benchmark,
        func_name: str,
        container_deployment: bool,
        container_uri: str,
    ) -> Function:
        raise RuntimeError("SonataFlow deployment does not support individual function creation.")

    def update_function(
        self,
        code_package: Benchmark,
        func: Function,
        container_deployment: bool,
        container_uri: str,
    ) -> Function:
        raise RuntimeError("SonataFlow deployment does not support individual function updates.")

    def create_function_trigger(self, func: Function, trigger_type: Trigger.TriggerType) -> Trigger:
        raise RuntimeError("SonataFlow deployment does not support function triggers.")

    def update_function_trigger(self, func: Function, trigger: Trigger):
        raise RuntimeError("SonataFlow deployment does not support function triggers.")

    def execute(
        self,
        code_package: Benchmark,
        trigger: Trigger,
        input: dict,
        repetitions: int,
        sync: bool,
    ) -> List[ExecutionResult]:
        return Local.execute(self, code_package, trigger, input, repetitions, sync)

    def get_function(self, code_package: Benchmark, func_name: str) -> Function:
        raise RuntimeError("Function retrieval is not supported in SonataFlow mode.")

    def prepare_experiment(self, benchmark: CloudBenchmark):
        return Local.prepare_experiment(self, benchmark)

    def shutdown(self) -> None:
        super().shutdown()
