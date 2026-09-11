"""GCP Workflows generator for SeBS workflow definitions."""

import uuid
from typing import Dict, Union, List, Set, Tuple

from sebs.faas.fsm import Generator, State, Task, Switch, Map, Parallel, Repeat, Loop, Branch


class GCPGenerator(Generator):
    """Generate GCP Workflows definitions from SeBS workflow FSMs."""

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
        """Wrap encoded steps in a GCP Workflows main definition."""
        payloads.append({"final": {"return": "${res}"}})

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
            elif isinstance(state, (Map, Parallel, Loop, Repeat)):
                if state.next:
                    queue.append(state.next)

        # Also add any states not reachable from root (shouldn't happen in well-formed FSMs)
        for name, state in self.states.items():
            if name not in visited:
                ordered.append(state)

        return ordered

    def generate(self) -> str:
        """Generate a serialized GCP Workflows definition."""
        self._ordered_states = self._topological_order()
        terminal_names = self._find_terminal_state_names()

        payloads: List[dict] = []
        for s in self._ordered_states:
            obj = self.encode_state(s)
            if isinstance(obj, dict):
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
            has_next = getattr(state, "next", None)
            if not has_next:
                terminals.add(name)
        return terminals

    def encode_task(self, state: Task) -> Union[dict, List[dict]]:
        """Encode a task state as an HTTP call step."""
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
        """Encode a switch state as a GCP Workflows switch step."""
        return {
            state.name: {
                "switch": [self._encode_case(c) for c in state.cases],
                "next": state.default,
            }
        }

    def _encode_case(self, case: Switch.Case) -> dict:
        """Encode a switch case into a GCP Workflows condition."""
        cond = "res." + case.var + " " + case.op + " " + str(case.val)
        return {"condition": "${" + cond + "}", "next": case.next}

    def encode_map(self, state: Map, res_var: str = "res") -> Union[dict, List[dict]]:
        """Encode a Map state as GCP Workflows steps.

        Args:
            state: Map state to encode.
            res_var: Variable name that holds the current result dict.  Defaults
                to ``"res"`` for top-level maps; pass a branch-specific variable
                when encoding maps inside parallel branches to avoid cross-branch
                interference via the shared ``res`` variable.

        Returns:
            List of step dicts for the map.
        """
        if isinstance(state.funcs, dict):
            first_state = next(iter(state.funcs.values()))
            func_name = first_state["func_name"]
        else:
            func_name = state.funcs[0]

        id = self._workflow_name + "_" + "map" + str(uuid.uuid4())[0:8]
        self._map_funcs[id] = (self._func_triggers[func_name], state.common_params)

        # Write map output to a separate var so the original dict is preserved.
        # Use dot-path assignment (res_var.array = map_res_NAME) to update only
        # the array key, keeping all other context fields intact.
        map_res_var = "map_res_" + state.name.replace("-", "_")

        if state.common_params:
            enrich_id = "enrich_" + state.name
            enriched_var = "enriched_" + state.name.replace("-", "_")
            temp_var = "tmp_" + state.name.replace("-", "_")

            temp_dict: dict = {"array_element": "${elem}"}
            for p in state.common_params:
                temp_dict[p] = "${" + res_var + "." + p + "}"

            inner_steps: List[dict] = [
                {"build_" + enrich_id: {"assign": [{temp_var: temp_dict}]}},
                {
                    "append_"
                    + enrich_id: {
                        "assign": [
                            {enriched_var: "${list.concat(" + enriched_var + ", " + temp_var + ")}"}
                        ]
                    }
                },
            ]
            enrich_steps: List[dict] = [
                {"init_" + enrich_id: {"assign": [{enriched_var: []}]}},
                {
                    "loop_"
                    + enrich_id: {
                        "for": {
                            "value": "elem",
                            "in": "${" + res_var + "." + state.array + "}",
                            "steps": inner_steps,
                        }
                    }
                },
            ]
            call_step: dict = {
                state.name: {
                    "call": "experimental.executions.map",
                    "args": {"workflow_id": id, "arguments": "${" + enriched_var + "}"},
                    "result": map_res_var,
                }
            }
            return_steps: List[dict] = enrich_steps + [call_step]
        else:
            call_step = {
                state.name: {
                    "call": "experimental.executions.map",
                    "args": {
                        "workflow_id": id,
                        "arguments": "${" + res_var + "." + state.array + "}",
                    },
                    "result": map_res_var,
                }
            }
            return_steps = [call_step]
        # Update only the array key; all other context fields are preserved.
        assign_step: dict = {
            "assign_res_"
            + state.name: {"assign": [{res_var + "." + state.array: "${" + map_res_var + "}"}]}
        }
        steps: List[dict] = return_steps + [assign_step]
        if state.next:
            steps.append({"next_" + state.name: {"next": state.next}})
        return steps

    def _encode_branch(self, branch: Branch, shared_var: str) -> Tuple[List[dict], List[str]]:
        """Encode a single Parallel branch as a list of GCP Workflow steps.

        Each branch reads from ``shared_var``, processes its states in order,
        and writes its result back to ``shared_var``.  Because GCP Workflows
        parallel branches share the global variable namespace we write results
        into a branch-specific variable and later merge them.

        Args:
            branch: Branch definition containing sub-states.
            shared_var: Variable name to read input from.

        Returns:
            Tuple of (steps, extra_shared_vars).  ``extra_shared_vars`` lists
            any intermediate variables written inside the branch (e.g.
            ``map_res_*``) that must appear in the parallel step's ``shared``
            list.
        """
        from sebs.faas.fsm import State as FSMState

        steps: List[dict] = []
        extra_shared: List[str] = []
        # Resolve BFS order within the branch's own state dict
        b_states = {n: FSMState.deserialize(n, s) for n, s in branch.states.items()}
        visited: Set[str] = set()
        queue = [branch.root]
        ordered = []
        while queue:
            n = queue.pop(0)
            if n in visited or n not in b_states:
                continue
            visited.add(n)
            s = b_states[n]
            ordered.append(s)
            nxt = getattr(s, "next", None)
            if nxt:
                queue.append(nxt)
            if isinstance(s, Task) and s.failure:
                queue.append(s.failure)

        for s in ordered:
            if isinstance(s, Task):
                url = self._func_triggers[s.func_name]
                steps.append(
                    {
                        s.name: {
                            "call": "http.post",
                            "args": {
                                "url": url,
                                "body": "${" + shared_var + "}",
                                "timeout": self._func_timeout,
                            },
                            "result": shared_var,
                        }
                    }
                )
                steps.append(
                    {
                        "assign_res_"
                        + s.name: {"assign": [{shared_var: "${" + shared_var + ".body}"}]}
                    }
                )
            elif isinstance(s, Map):
                # Pass shared_var directly so encode_map reads/writes that variable
                # instead of the global "res".  This avoids cross-branch interference
                # when multiple parallel branches each contain a Map step.
                steps += self.encode_map(s, res_var=shared_var)  # type: ignore[arg-type]
                # map_res_<name> is written inside this branch — must be shared.
                map_res_var = "map_res_" + s.name.replace("-", "_")
                extra_shared.append(map_res_var)
        return steps, extra_shared

    def encode_parallel(self, state: Parallel) -> Union[dict, List[dict]]:
        """Encode a Parallel state as a GCP Workflows parallel block.

        Each branch runs concurrently with its own local copy of ``res``
        (since ``res`` is NOT in ``shared``).  Results are stored in
        branch-specific shared variables and merged into ``res`` afterwards.

        Args:
            state: Parallel state to encode.

        Returns:
            List of step dicts for the parallel block and result merge.
        """
        shared_vars = []
        extra_shared_all: List[str] = []
        gcp_branches = []
        for i, branch in enumerate(state.branches):
            # Use a per-branch local variable as the working variable throughout
            # the branch so that no branch writes to the outer "res".
            # The final value is stored in this shared var after the branch ends.
            var = "branch_res_" + state.name.replace("-", "_") + "_" + str(i)
            shared_vars.append(var)
            # Encode branch using var as both input (initialised to ${res}) and
            # working accumulator — _encode_branch takes the var name to use.
            branch_steps, extra_shared = self._encode_branch(branch, var)
            extra_shared_all.extend(extra_shared)
            # Seed the per-branch variable from the outer res before starting.
            seed_step = {"seed_" + var: {"assign": [{var: "${res}"}]}}
            branch_name = "branch_" + state.name.replace("-", "_") + "_" + str(i)
            gcp_branches.append({branch_name: {"steps": [seed_step] + branch_steps}})

        # GCP Workflows requires shared variables to be initialized in the outer
        # scope before the parallel step references them.
        all_shared_vars = shared_vars + extra_shared_all
        init_assigns = [{v: None} for v in all_shared_vars]
        init_step = {"init_" + state.name: {"assign": init_assigns}}

        parallel_step = {
            state.name: {
                "parallel": {
                    # Only branch_res_* and map_res_* vars are shared; "res" is NOT
                    # listed so each branch gets its own local copy — no cross-branch
                    # interference when two branches both contain Map steps.
                    "shared": all_shared_vars,
                    "branches": gcp_branches,
                }
            }
        }
        # Merge: build a single dict keyed by branch root name using YAML dict syntax.
        merged_dict = {
            branch.root: "${" + var + "}" for var, branch in zip(shared_vars, state.branches)
        }
        merge_step = {"merge_" + state.name: {"assign": [{"res": merged_dict}]}}
        steps: List[dict] = [init_step, parallel_step, merge_step]
        if state.next:
            steps.append({"next_" + state.name: {"next": state.next}})
        return steps

    def encode_loop(self, state: Loop) -> Union[dict, List[dict]]:
        """Encode a loop state as a GCP Workflows for step."""
        url = self._func_triggers[state.func_name]

        return {
            state.name: {
                "for": {
                    "value": "val",
                    "index": "idx",
                    "in": "${res." + state.array + "}",
                    "steps": [
                        {
                            "body": {
                                "call": "http.post",
                                "args": {
                                    "url": url,
                                    "body": "${val}",
                                    "timeout": self._func_timeout,
                                },
                            }
                        }
                    ],
                }
            }
        }

    def generate_maps(self):
        """Generate auxiliary map sub-workflow definitions."""
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
                                        "args": {
                                            "url": url,
                                            "body": "${elem}",
                                            "timeout": self._func_timeout,
                                        },
                                        "result": "elem",
                                    }
                                },
                                {"ret": {"return": "${elem.body}"}},
                            ],
                        }
                    }
                ),
            )
