import json
from typing import Dict, List, Union

from sebs.faas.fsm import Generator, State, Task, Switch, Map, Repeat, Loop, Parallel


class SonataFlowGenerator(Generator):
    """
    Translate a SeBS workflow definition into a SonataFlow Serverless Workflow definition.
    Currently supports task, switch, map (as foreach), repeat, loop and parallel constructs
    with a best-effort mapping to SonataFlow branches.
    """

    def __init__(self, workflow_id: str, bindings: Dict[str, Dict[str, str]]):
        super().__init__(export_func=lambda obj: json.dumps(obj, indent=2))
        self._workflow_id = workflow_id
        self._bindings = bindings
        self._functions: Dict[str, Dict[str, str]] = {}

    def _function_ref(self, func_name: str) -> Dict[str, str]:
        binding = self._bindings.get(func_name)
        if not binding:
            raise ValueError(f"No binding found for function {func_name}")
        ref_name = binding.get("workflow_function_name", func_name)
        if ref_name not in self._functions:
            host = binding["host"]
            port = binding["port"]
            url = f"http://{host}:{port}/"
            self._functions[ref_name] = {"name": ref_name, "operation": url}
        return {"refName": ref_name}

    def _default_action(self, func_name: str, payload_ref: str = "${ . }") -> Dict[str, object]:
        ref = self._function_ref(func_name)
        ref["arguments"] = {"payload": payload_ref}
        return {"name": func_name, "functionRef": ref}

    def postprocess(self, payloads: List[dict]) -> dict:
        return {
            "id": self._workflow_id,
            "name": self._workflow_id,
            "version": "0.1",
            "description": "Auto-generated from SeBS workflow definition.",
            "functions": list(self._functions.values()),
            "start": self.root.name,
            "states": payloads,
        }

    def encode_task(self, state: Task) -> Union[dict, List[dict]]:
        payload: Dict[str, object] = {
            "name": state.name,
            "type": "operation",
            "actions": [self._default_action(state.func_name, "${ . }")],
        }
        if state.next:
            payload["transition"] = state.next
        else:
            payload["end"] = True
        if state.failure is not None:
            payload["onErrors"] = [{"transition": state.failure}]
        return payload

    def encode_switch(self, state: Switch) -> Union[dict, List[dict]]:
        def _condition(case: Switch.Case) -> str:
            # Serverless Workflow uses jq-like expressions; keep it simple.
            return f"{case.var} {case.op} {json.dumps(case.val)}"

        return {
            "name": state.name,
            "type": "switch",
            "dataConditions": [
                {"condition": _condition(c), "transition": c.next} for c in state.cases
            ],
            "defaultCondition": {"transition": state.default} if state.default else {"end": True},
        }

    def encode_map(self, state: Map) -> Union[dict, List[dict]]:
        iteration_param = "item"
        action_args = "${ " + iteration_param + " }"
        if state.common_params:
            # Merge map element with selected common parameters.
            merged = {"array_element": "${ " + iteration_param + " }"}
            for param in [p.strip() for p in state.common_params.split(",") if p.strip()]:
                merged[param] = "${ ." + param + " }"
            action_args = merged  # type: ignore

        payload: Dict[str, object] = {
            "name": state.name,
            "type": "foreach",
            "inputCollection": "${ ." + state.array + " }",
            "outputCollection": "${ ." + state.array + " }",
            "iterationParam": iteration_param,
            "actions": [self._default_action(state.root, action_args)],
        }
        if state.next:
            payload["transition"] = state.next
        else:
            payload["end"] = True
        return payload

    def encode_repeat(self, state: Repeat) -> Union[dict, List[dict]]:
        # Encode as a foreach over a generated range.
        iterations = list(range(state.count))
        payload: Dict[str, object] = {
            "name": state.name,
            "type": "foreach",
            "inputCollection": iterations,
            "iterationParam": "idx",
            "actions": [self._default_action(state.func_name, "${ . }")],
        }
        if state.next:
            payload["transition"] = state.next
        else:
            payload["end"] = True
        return payload

    def encode_loop(self, state: Loop) -> Union[dict, List[dict]]:
        payload: Dict[str, object] = {
            "name": state.name,
            "type": "foreach",
            "inputCollection": "${ ." + state.array + " }",
            "iterationParam": "item",
            "actions": [self._default_action(state.func_name, "${ .item }")],
        }
        if state.next:
            payload["transition"] = state.next
        else:
            payload["end"] = True
        return payload

    def _encode_branch(self, subworkflow: dict) -> Dict[str, object]:
        states = {n: State.deserialize(n, s) for n, s in subworkflow["states"].items()}
        payloads: List[dict] = []
        for s in states.values():
            obj = self.encode_state(s)
            if isinstance(obj, list):
                payloads.extend(obj)
            else:
                payloads.append(obj)
        return {"name": subworkflow["root"], "states": payloads}

    def encode_parallel(self, state: Parallel) -> Union[dict, List[dict]]:
        branches = [self._encode_branch(sw) for sw in state.funcs]
        payload: Dict[str, object] = {"name": state.name, "type": "parallel", "branches": branches}
        if state.next:
            payload["transition"] = state.next
        else:
            payload["end"] = True
        return payload
