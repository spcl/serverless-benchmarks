import uuid
from typing import Dict, Union, List, Optional, Set

from sebs.faas.fsm import Generator, State, Task, Switch, Map, Parallel, Repeat, Loop


class GCPGenerator(Generator):
    def __init__(
        self,
        workflow_name: str,
        func_triggers: Dict[str, str],
        func_timeout: int = 1800,
    ):
        """Initialize GCP Workflows YAML generator.

        Args:
            workflow_name: Name of the workflow being generated.
            func_triggers: Map from function name to HTTP trigger URL.
            func_timeout: Timeout in seconds for http.post calls (default 1800).
        """
        super().__init__()
        self._workflow_name = workflow_name
        self._func_triggers = func_triggers
        self._func_timeout = func_timeout
        # Maps workflow_id -> (url, common_params_list_or_None)
        self._map_funcs: Dict[str, tuple] = dict()
        self._ordered_states: List[State] = []

    def postprocess(self, payloads: List[dict]) -> dict:
        payloads.append({"final": {"return": ["${res}"]}})

        definition = {"main": {"params": ["res"], "steps": payloads}}

        return definition

    def _topological_order(self) -> List[State]:
        """Return states in BFS order starting from root, visiting all reachable states."""
        visited: Set[str] = set()
        ordered: List[State] = []
        queue: List[str] = [self.root.name]

        while queue:
            name = queue.pop(0)
            if name in visited or name not in self.states:
                continue
            visited.add(name)
            state = self.states[name]
            ordered.append(state)
            # Enqueue successors
            if isinstance(state, Task):
                if state.next:
                    queue.append(state.next)
                if state.failure:
                    queue.append(state.failure)
            elif isinstance(state, Switch):
                for case in state.cases:
                    queue.append(case.next)
                if state.default:
                    queue.append(state.default)

        # Also add any states not reachable from root (shouldn't happen in well-formed FSMs)
        for name, state in self.states.items():
            if name not in visited:
                ordered.append(state)

        return ordered

    def generate(self) -> str:
        self._ordered_states = self._topological_order()
        terminal_names = self._find_terminal_state_names()

        payloads: List[dict] = []
        for s in self._ordered_states:
            obj = self.encode_state(s)
            if isinstance(obj, dict):
                encoded_name = list(obj.keys())[0]
                payloads.append(obj)
                # Add explicit jump to final for terminal states that aren't last
                if s.name in terminal_names and self._ordered_states[-1].name != s.name:
                    payloads.append({"goto_final_" + s.name: {"next": "final"}})
            elif isinstance(obj, list):
                payloads += obj
                # After the last step for this state, add jump to final if terminal
                if s.name in terminal_names and self._ordered_states[-1].name != s.name:
                    payloads.append({"goto_final_" + s.name: {"next": "final"}})
            else:
                raise ValueError("Unknown encoded state returned.")

        definition = self.postprocess(payloads)
        return self._export_func(definition)

    def _find_terminal_state_names(self) -> Set[str]:
        """Find states that have no next pointer (end of a path)."""
        terminals: Set[str] = set()
        for name, state in self.states.items():
            if isinstance(state, Task) and not state.next:
                terminals.add(name)
        return terminals

    def encode_task(self, state: Task) -> Union[dict, List[dict]]:
        url = self._func_triggers[state.func_name]

        if state.failure:
            call_step: dict = {
                state.name: {
                    "try": {
                        "call": "http.post",
                        "args": {"url": url, "body": "${res}", "timeout": self._func_timeout},
                        "result": "res",
                    },
                    "except": {
                        "as": "e",
                        "steps": [
                            {"jump_" + state.name: {"next": state.failure}},
                        ],
                    },
                }
            }
            assign_step = {"assign_res_" + state.name: {"assign": [{"res": "${res.body}"}]}}
            steps: list = [call_step, assign_step]
            if state.next:
                steps.append({"next_" + state.name: {"next": state.next}})
            return steps
        else:
            plain_steps: list = [
                {
                    state.name: {
                        "call": "http.post",
                        "args": {"url": url, "body": "${res}", "timeout": self._func_timeout},
                        "result": "res",
                    }
                },
                {"assign_res_" + state.name: {"assign": [{"res": "${res.body}"}]}},
            ]
            if state.next:
                plain_steps.append({"next_" + state.name: {"next": state.next}})
            return plain_steps

    def encode_switch(self, state: Switch) -> Union[dict, List[dict]]:
        return {
            state.name: {
                "switch": [self._encode_case(c) for c in state.cases],
                "next": state.default,
            }
        }

    def _encode_case(self, case: Switch.Case) -> dict:
        cond = "res." + case.var + " " + case.op + " " + str(case.val)
        return {"condition": "${" + cond + "}", "next": case.next}

    def encode_map(self, state: Map) -> Union[dict, List[dict]]:
        if isinstance(state.funcs, dict):
            first_state = next(iter(state.funcs.values()))
            func_name = first_state["func_name"]
        else:
            func_name = state.funcs[0]

        id = self._workflow_name + "_" + "map" + str(uuid.uuid4())[0:8]
        self._map_funcs[id] = (self._func_triggers[func_name], state.common_params)

        if state.common_params:
            # Build enriched array: [{array_element: elem, ...common_params}, ...]
            # GCP Workflows assign uses YAML dict syntax (not expression ${}) for maps.
            enrich_id = "enrich_" + state.name
            enriched_var = "enriched_" + state.name.replace("-", "_")
            temp_var = "tmp_" + state.name.replace("-", "_")

            # Build the temp dict using YAML dict syntax in assign
            temp_dict: dict = {"array_element": "${elem}"}
            for p in state.common_params:
                temp_dict[p] = "${res." + p + "}"

            inner_steps = [
                {
                    "build_" + enrich_id: {
                        "assign": [{temp_var: temp_dict}]
                    }
                },
                {
                    "append_" + enrich_id: {
                        "assign": [
                            {enriched_var: "${list.concat(" + enriched_var + ", " + temp_var + ")}"}
                        ]
                    }
                },
            ]
            enrich_steps = [
                {"init_" + enrich_id: {"assign": [{enriched_var: []}]}},
                {
                    "loop_" + enrich_id: {
                        "for": {
                            "value": "elem",
                            "in": "${res." + state.array + "}",
                            "steps": inner_steps,
                        }
                    }
                },
            ]
            call_step = {
                state.name: {
                    "call": "experimental.executions.map",
                    "args": {"workflow_id": id, "arguments": "${" + enriched_var + "}"},
                    "result": "res",
                }
            }
            return_steps = [*enrich_steps, call_step]
        else:
            call_step = {
                state.name: {
                    "call": "experimental.executions.map",
                    "args": {"workflow_id": id, "arguments": "${res." + state.array + "}"},
                    "result": "res",
                }
            }
            return_steps = [call_step]
        # Wrap the list result back into a dict so downstream tasks can access it by key
        assign_step = {
            "assign_res_" + state.name: {
                "assign": [{"res": {state.array: "${res}"}}]
            }
        }
        steps = return_steps + [assign_step]
        if state.next:
            steps.append({"next_" + state.name: {"next": state.next}})
        return steps

    def encode_parallel(self, state: Parallel) -> Union[dict, List[dict]]:
        branches = []
        for fn in state.funcs:
            url = self._func_triggers[fn]
            branches.append({
                "call": "http.post",
                "args": {"url": url, "body": "${res}"},
                "result": "res",
            })

        return {
            state.name: {
                "parallel": {"branches": [{"steps": [{"invoke": b}]} for b in branches]},
                "next": state.next,
            }
        }

    def encode_loop(self, state: Loop) -> Union[dict, List[dict]]:
        url = self._func_triggers[state.func_name]

        return {
            state.name: {
                "for": {
                    "value": "val",
                    "index": "idx",
                    "in": "${res."+state.array+"}",
                    "steps": [
                        {
                            "body": {
                                "call": "http.post",
                                "args": {"url": url, "body": "${val}", "timeout": self._func_timeout}
                            }
                        }
                    ]
                }
            }
        }

    def generate_maps(self):
        for workflow_id, (url, common_params) in self._map_funcs.items():
            yield (
                workflow_id,
                self._export_func(
                    {
                        "main": {
                            "params": ["elem"],
                            "steps": [
                                {
                                    "map": {
                                        "call": "http.post",
                                        "args": {"url": url, "body": "${elem}", "timeout": self._func_timeout},
                                        "result": "elem",
                                    }
                                },
                                {"ret": {"return": "${elem.body}"}},
                            ],
                        }
                    }
                ),
            )
