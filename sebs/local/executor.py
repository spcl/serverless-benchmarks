import concurrent.futures
import copy
import json
from typing import Any, Dict, List, Optional

import requests

from sebs.faas.fsm import Loop, Map, Parallel, Repeat, State, Switch, Task


def _get_var(obj: Any, path: str) -> Any:
    parts = [segment.strip() for segment in path.split(".") if segment.strip()]
    value = obj
    for part in parts:
        try:
            value = value[part]
        except (KeyError, TypeError):
            raise WorkflowExecutionError(
                f"Missing key '{part}' while reading path '{path}' in object {value!r}"
            )
    return value


def _set_var(obj: Any, value: Any, path: str):
    parts = [segment.strip() for segment in path.split(".") if segment.strip()]
    target = obj
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value


class WorkflowExecutionError(RuntimeError):
    pass


class LocalWorkflowExecutor:
    """
    Execute workflow definitions (benchmarks/600.workflows/*/definition.json)
    by invoking local function containers directly. Mirrors the orchestration
    semantics implemented in Azure/GCP wrappers.
    """

    def __init__(self, definition_path: str, bindings: Dict[str, Dict[str, str]]):
        self._definition_path = definition_path
        with open(definition_path) as definition_file:
            definition = json.load(definition_file)
        self._states = {
            name: State.deserialize(name, payload) for name, payload in definition["states"].items()
        }
        self._root = definition["root"]
        self._bindings = bindings

    def run(self, payload: dict, request_id: str) -> dict:
        return self._run_state_machine(self._states, self._root, payload, request_id)

    def _run_state_machine(
        self, states: Dict[str, State], root_name: str, payload: dict, request_id: str
    ) -> dict:
        current = states[root_name]
        result = payload
        while current:
            if isinstance(current, Task):
                result, current = self._execute_task(states, current, result, request_id)
            elif isinstance(current, Switch):
                current = self._execute_switch(states, current, result)
            elif isinstance(current, Map):
                result = self._execute_map(current, result, request_id)
                current = states.get(current.next)
            elif isinstance(current, Repeat):
                result = self._execute_repeat(current, result, request_id)
                current = states.get(current.next)
            elif isinstance(current, Loop):
                self._execute_loop(current, result, request_id)
                current = states.get(current.next)
            elif isinstance(current, Parallel):
                result = self._execute_parallel(current, result, request_id)
                current = states.get(current.next)
            else:
                raise WorkflowExecutionError(f"Undefined state: {current}")
        return result

    def _call_function(self, func_name: str, payload: dict, request_id: str) -> dict:
        if func_name not in self._bindings:
            raise WorkflowExecutionError(f"No binding found for function {func_name}")
        binding = self._bindings[func_name]
        url = f"http://{binding['host']}:{binding['port']}/"
        body_payload = payload
        if isinstance(payload, dict):
            body_payload = dict(payload)
            body_payload.setdefault("request_id", request_id)
            body_payload.setdefault("request-id", request_id)
        response = requests.post(
            url,
            json={"payload": body_payload, "request_id": request_id},
            timeout=900,
        )
        if response.status_code >= 300:
            raise WorkflowExecutionError(
                f"Invocation of {func_name} at {url} failed with status {response.status_code}"
            )
        body = response.json()
        if isinstance(body, dict):
            candidate = body
            if "result" in body and isinstance(body["result"], dict):
                candidate = body["result"].get("output", candidate)
            if isinstance(candidate, dict) and "payload" in candidate:
                return candidate["payload"]
            if "payload" in body:
                return body["payload"]
        return body

    def _execute_task(
        self, states: Dict[str, State], state: Task, data: dict, request_id: str
    ) -> (dict, Optional[State]):
        try:
            result = self._call_function(state.func_name, data, request_id)
        except Exception:
            if state.failure:
                return data, states.get(state.failure)
            raise
        return result, states.get(state.next)

    def _execute_switch(
        self, states: Dict[str, State], switch: Switch, data: dict
    ) -> Optional[State]:
        ops = {
            "<": lambda x, y: x < y,
            "<=": lambda x, y: x <= y,
            "==": lambda x, y: x == y,
            ">=": lambda x, y: x >= y,
            ">": lambda x, y: x > y,
        }
        for case in switch.cases:
            lhs = _get_var(data, case.var)
            if ops[case.op](lhs, case.val):
                return states.get(case.next)
        if switch.default:
            return states.get(switch.default)
        return None

    def _build_map_payload(self, element: Any, data: dict, common_params: Optional[str]) -> dict:
        if not common_params:
            return element
        payload: Dict[str, Any] = {"array_element": element}
        for param in [entry.strip() for entry in common_params.split(",") if entry.strip()]:
            payload[param] = _get_var(data, param)
        return payload

    def _execute_map(self, map_state: Map, data: dict, request_id: str) -> dict:
        array = _get_var(data, map_state.array)
        if not isinstance(array, list):
            raise WorkflowExecutionError(
                f"Map state {map_state.name} expects list at {map_state.array}"
            )
        map_states = {n: State.deserialize(n, s) for n, s in map_state.funcs.items()}
        results: List[Any] = []
        tasks: List[Any] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(len(array), 1)) as executor:
            for element in array:
                payload = self._build_map_payload(element, data, map_state.common_params)
                tasks.append(
                    executor.submit(
                        self._run_state_machine,
                        map_states,
                        map_state.root,
                        payload,
                        request_id,
                    )
                )
            for task in tasks:
                results.append(task.result())
        _set_var(data, results, map_state.array)
        return data

    def _execute_repeat(self, repeat: Repeat, data: dict, request_id: str) -> dict:
        result = data
        for _ in range(repeat.count):
            result = self._call_function(repeat.func_name, result, request_id)
        return result

    def _execute_loop(self, loop: Loop, data: dict, request_id: str):
        array = _get_var(data, loop.array)
        for element in array:
            self._call_function(loop.func_name, element, request_id)

    def _execute_parallel(self, parallel: Parallel, data: dict, request_id: str) -> dict:
        results: Dict[str, Any] = {}
        tasks: List[concurrent.futures.Future] = []
        labels: List[str] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(parallel.funcs)) as executor:
            for branch in parallel.funcs:
                branch_states = {n: State.deserialize(n, s) for n, s in branch["states"].items()}
                labels.append(branch["root"])
                tasks.append(
                    executor.submit(
                        self._run_state_machine,
                        branch_states,
                        branch["root"],
                        copy.deepcopy(data),
                        request_id,
                    )
                )
            for label, future in zip(labels, tasks):
                results[label] = future.result()
        return results
