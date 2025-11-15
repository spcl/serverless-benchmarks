import logging
import os
from typing import Dict, List, Optional

from sebs.faas.function import FunctionConfig, Workflow
from sebs.local.function import LocalFunction
from sebs.local.triggers import WorkflowLocalTrigger


class LocalWorkflow(Workflow):
    def __init__(
        self,
        name: str,
        functions: List[LocalFunction],
        benchmark: str,
        workflow_id: str,
        code_package_hash: str,
        cfg: FunctionConfig,
        definition_path: str,
        function_bindings: Dict[str, Dict],
    ):
        super().__init__(benchmark, name, code_package_hash, cfg)
        self._functions: Dict[str, LocalFunction] = {func.name: func for func in functions}
        self.workflow_id = workflow_id
        self.definition_path = definition_path
        self.function_bindings = function_bindings
        self.needs_refresh = False

    @property
    def functions(self) -> List[LocalFunction]:
        return list(self._functions.values())

    def set_functions(self, functions: List[LocalFunction]):
        self._functions = {func.name: func for func in functions}

    def update_function(self, func: LocalFunction):
        self._functions[func.name] = func

    @staticmethod
    def typename() -> str:
        return "Local.Workflow"

    def serialize(self) -> dict:
        serialized = {
            **super().serialize(),
            "functions": [func.serialize() for func in self._functions.values()],
            "definition_path": self.definition_path,
            "function_bindings": self.function_bindings,
            "workflow_id": self.workflow_id,
        }
        serialized["triggers"] = []
        return serialized

    @staticmethod
    def deserialize(cached_config: dict) -> "LocalWorkflow":
        funcs: List[LocalFunction] = []
        missing_function = False
        for entry in cached_config["functions"]:
            try:
                funcs.append(LocalFunction.deserialize(entry))
            except RuntimeError as exc:
                logging.getLogger(__name__).warning(
                    "Skipping cached function for workflow %s: %s",
                    cached_config.get("name", "<unknown>"),
                    exc,
                )
                missing_function = True
        cfg = FunctionConfig.deserialize(cached_config["config"])
        workflow = LocalWorkflow(
            cached_config["name"],
            funcs,
            cached_config["benchmark"],
            cached_config.get("workflow_id", cached_config["name"]),
            cached_config["hash"],
            cfg,
            cached_config.get("definition_path", ""),
            cached_config.get("function_bindings", {}),
        )
        workflow.needs_refresh = missing_function
        if os.path.exists(workflow.definition_path):
            workflow.add_trigger(
                WorkflowLocalTrigger(workflow.definition_path, workflow.function_bindings)
            )
        return workflow
