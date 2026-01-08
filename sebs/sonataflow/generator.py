import json
from typing import Dict, List, Optional, Union

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
        self._uses_errors = False  # Track if any state uses onErrors
        # Unwrap SeBS local server responses so workflow state data stays as payload.
        self._action_results_expr_inner = ".result.output.payload // .payload // ."
        self._action_results_expr = f"${{ {self._action_results_expr_inner} }}"

    def _function_ref(self, func_name: str) -> Dict[str, str]:
        binding = self._bindings.get(func_name)
        if not binding:
            raise ValueError(f"No binding found for function {func_name}")
        ref_name = binding.get("workflow_function_name", func_name)
        if ref_name not in self._functions:
            host = binding["host"]
            port = binding["port"]
            # SonataFlow custom REST function format: operation is "rest:METHOD:URL"
            # Use absolute URL since we know the host and port
            url = f"http://{host}:{port}/"
            self._functions[ref_name] = {
                "name": ref_name,
                "operation": f"rest:post:{url}",
                "type": "custom",
            }
        return {"refName": ref_name}

    def _default_action(self, func_name: str, payload_ref: str = "${ . }") -> Dict[str, object]:
        ref = self._function_ref(func_name)
        request_id_expr = '${ .request_id // .requestId // .["request-id"] }'
        ref["arguments"] = {"payload": payload_ref, "request_id": request_id_expr}
        return {
            "name": func_name,
            "functionRef": ref,
            "actionDataFilter": {"results": self._action_results_expr},
        }

    def postprocess(self, payloads: List[dict]) -> dict:
        workflow_def = {
            "id": self._workflow_id,
            "name": self._workflow_id,
            "version": "0.1",
            "specVersion": "0.8",
            "description": "Auto-generated from SeBS workflow definition.",
            "functions": list(self._functions.values()),
            "start": self.root.name,
            "states": payloads,
        }
        # Add error definitions if any state uses onErrors
        if self._uses_errors:
            workflow_def["errors"] = [{"name": "workflow_error", "code": "*"}]  # Catch all errors
        return workflow_def

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
            self._uses_errors = True
            payload["onErrors"] = [{"errorRef": "workflow_error", "transition": state.failure}]
        return payload

    def encode_switch(self, state: Switch) -> Union[dict, List[dict]]:
        def _condition(case: Switch.Case) -> str:
            # Serverless Workflow uses jq expressions wrapped in ${ }
            var = case.var.strip()
            needs_dot_prefix = not var.startswith((".", "$")) and not any(ch in var for ch in " ()|+*/-")

            # Ensure field path has dot prefix for jq
            if needs_dot_prefix:
                var = "." + self._quote_field_path(var)
            elif var.startswith(".") and "." in var[1:]:
                # Already has a dot prefix
                var = "." + self._quote_field_path(var[1:])

            # Wrap the condition in ${ } as per SonataFlow documentation
            return f"${{ {var} {case.op} {json.dumps(case.val)} }}"

        return {
            "name": state.name,
            "type": "switch",
            "dataConditions": [
                {"condition": _condition(c), "transition": c.next} for c in state.cases
            ],
            "defaultCondition": {"transition": state.default} if state.default else {"end": True},
        }

    def _quote_field_path(self, path: str) -> str:
        """Return field path as-is for jq expressions.
        Simple dot notation like "astros.people" works fine in jq.
        """
        return path

    def encode_map(self, state: Map) -> Union[dict, List[dict]]:
        iteration_param = "item"
        action_args = "${ ." + iteration_param + " }"
        if state.common_params:
            # Merge map element with selected common parameters.
            merged = {"array_element": "${ ." + iteration_param + " }"}
            for param in [p.strip() for p in state.common_params.split(",") if p.strip()]:
                quoted_param = self._quote_field_path(param)
                merged[param] = "${ ." + quoted_param + " }"
            action_args = merged  # type: ignore

        # Resolve the actual function name from the root state
        # state.root is the name of the nested state, state.funcs contains the state definitions
        root_state_def = state.funcs.get(state.root, {})
        func_name = root_state_def.get("func_name", state.root)

        quoted_array = self._quote_field_path(state.array)
        output_array = getattr(state, "output_array", state.array)
        quoted_output = self._quote_field_path(output_array)
        payload: Dict[str, object] = {
            "name": state.name,
            "type": "foreach",
            "inputCollection": "${ ." + quoted_array + " }",
            "outputCollection": "${ ." + quoted_output + " }",
            "iterationParam": iteration_param,
            "actions": [self._default_action(func_name, action_args)],
        }
        if state.next:
            payload["transition"] = state.next
        else:
            payload["end"] = True
        return payload

    def encode_repeat(self, state: Repeat) -> Union[dict, List[dict]]:
        # Encode as a foreach over a generated range.
        iterations = list(range(state.count))
        input_expr = f"${{ {json.dumps(iterations)} }}"
        payload: Dict[str, object] = {
            "name": state.name,
            "type": "foreach",
            "inputCollection": input_expr,
            "iterationParam": "idx",
            "actions": [self._default_action(state.func_name, "${ . }")],
        }
        if state.next:
            payload["transition"] = state.next
        else:
            payload["end"] = True
        return payload

    def encode_loop(self, state: Loop) -> Union[dict, List[dict]]:
        quoted_array = self._quote_field_path(state.array)
        payload: Dict[str, object] = {
            "name": state.name,
            "type": "foreach",
            "inputCollection": "${ ." + quoted_array + " }",
            "iterationParam": "item",
            "actions": [self._default_action(state.func_name, "${ .item }")],
        }
        if state.next:
            payload["transition"] = state.next
        else:
            payload["end"] = True
        return payload

    def _encode_branch(self, subworkflow: dict) -> Dict[str, object]:
        """
        For SonataFlow, branches are flat lists of actions. We flatten the root state
        of each subworkflow to a single action by selecting the function name.
        """
        states = {n: State.deserialize(n, s) for n, s in subworkflow["states"].items()}
        root_state = states.get(subworkflow["root"])
        if not root_state:
            raise ValueError(f"Root state {subworkflow['root']} not found in subworkflow")

        func_name = None
        if isinstance(root_state, Task):
            func_name = root_state.func_name
        elif isinstance(root_state, Map):
            # Use the mapped state's root function as the branch action.
            root_def = root_state.funcs.get(root_state.root, {})
            func_name = root_def.get("func_name", root_state.root)
        elif isinstance(root_state, Repeat):
            func_name = root_state.func_name
        elif isinstance(root_state, Loop):
            func_name = root_state.func_name
        else:
            raise ValueError(
                f"Parallel branches currently support Task/Map/Repeat/Loop root states, got {type(root_state).__name__}"
            )

        results_expr = (
            f"${{ {{\"{subworkflow['root']}\": {self._action_results_expr_inner}}} }}"
        )
        action = self._default_action(func_name, "${ . }")
        action["actionDataFilter"] = {"results": results_expr}
        return {"name": subworkflow["root"], "actions": [action]}

    def encode_parallel(self, state: Parallel) -> Union[dict, List[dict]]:
        branch_roots: List[State] = []
        has_complex = False
        for subworkflow in state.funcs:
            states = {n: State.deserialize(n, s) for n, s in subworkflow["states"].items()}
            root_state = states.get(subworkflow["root"])
            if root_state is None:
                raise ValueError(f"Root state {subworkflow['root']} not found in subworkflow")
            branch_roots.append(root_state)
            if not isinstance(root_state, Task):
                has_complex = True

        if not has_complex:
            branches = [self._encode_branch(sw) for sw in state.funcs]
            payload: Dict[str, object] = {"name": state.name, "type": "parallel", "branches": branches}
            if state.next:
                payload["transition"] = state.next
            else:
                payload["end"] = True
            return payload

        def _clone_state(root: State, name: str, next_name: Optional[str]) -> State:
            if isinstance(root, Task):
                return Task(name, root.func_name, next_name, root.failure)
            if isinstance(root, Map):
                return Map(name, root.funcs, root.array, root.root, next_name, root.common_params)
            if isinstance(root, Repeat):
                return Repeat(name, root.func_name, root.count, next_name)
            if isinstance(root, Loop):
                return Loop(name, root.func_name, root.array, next_name)
            raise ValueError(
                f"Parallel branch {name} uses unsupported root state type {type(root).__name__}"
            )

        encoded_states: List[dict] = []
        for idx, root in enumerate(branch_roots):
            branch_name = state.name if idx == 0 else root.name
            next_name = (
                branch_roots[idx + 1].name if idx < len(branch_roots) - 1 else state.next
            )
            cloned = _clone_state(root, branch_name, next_name)
            if isinstance(cloned, Map) and idx < len(branch_roots) - 1:
                cloned.output_array = f"_parallel_{state.name}_{idx}_results"
            encoded = self.encode_state(cloned)
            if isinstance(encoded, list):
                encoded_states.extend(encoded)
            else:
                encoded_states.append(encoded)
        return encoded_states
