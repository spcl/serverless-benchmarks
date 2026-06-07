from typing import Dict, List, Union, Any
import numbers
import uuid

from sebs.faas.fsm import Generator, Task, Switch, Map, Repeat, Loop


class SFNGenerator(Generator):
    def __init__(self, func_arns: Dict[str, str]):
        super().__init__()
        self._func_arns = func_arns

    def postprocess(self, payloads: List[dict]) -> dict:
        def _nameless(p: dict) -> dict:
            del p["Name"]
            return p

        state_payloads = {p["Name"]: _nameless(p) for p in payloads}

        definition = {
            "Comment": "SeBS auto-generated benchmark",
            "StartAt": self.root.name,
            "States": state_payloads,
        }

        return definition

    def encode_task(self, state: Task) -> Union[dict, List[dict]]:
        payload: Dict[str, Any] = {
            "Name": state.name,
            "Type": "Task",
            "Resource": self._func_arns[state.func_name]
        }

        if state.next:
            payload["Next"] = state.next
        else:
            payload["End"] = True

        if state.failure:
            payload["Catch"] = [
                {"ErrorEquals": ["States.ALL"], "Next": state.failure}
            ]

        return payload

    def encode_switch(self, state: Switch) -> Union[dict, List[dict]]:
        choises = [self._encode_case(c) for c in state.cases]
        return {
            "Name": state.name,
            "Type": "Choice",
            "Choices": choises,
            "Default": state.default
        }

    def _encode_case(self, case: Switch.Case) -> dict:
        type = "Numeric" if isinstance(case.val, numbers.Number) else "String"
        comp = {
            "<": "LessThan",
            "<=": "LessThanEquals",
            "==": "Equals",
            ">=": "GreaterThanEquals",
            ">": "GreaterThan",
        }
        cond = type + comp[case.op]

        return {"Variable": "$." + case.var, cond: case.val, "Next": case.next}

    def encode_map(self, state: Map) -> Union[dict, List[dict]]:
        map_func_name = "func_" + str(uuid.uuid4())[:8]

        # state.funcs can be a dict of nested states or a list of function names
        if isinstance(state.funcs, dict):
            # Get func_name from the first nested task state
            first_state = next(iter(state.funcs.values()))
            func_name = first_state["func_name"]
        else:
            func_name = state.funcs[0]

        payload: Dict[str, Any] = {
            "Name": state.name,
            "Type": "Map",
            "ItemsPath": "$." + state.array,
            "Iterator": {
                "StartAt": map_func_name,
                "States": {
                    map_func_name: {
                        "Type": "Task",
                        "Resource": self._func_arns[func_name],
                        "End": True,
                    }
                },
            },
        }

        if state.common_params:
            item_selector: Dict[str, str] = {"array_element.$": "$$.Map.Item.Value"}
            for p in state.common_params:
                item_selector[f"{p}.$"] = f"$.{p}"
            payload["ItemSelector"] = item_selector

        payload["ResultPath"] = "$." + state.array

        if state.next:
            payload["Next"] = state.next
        else:
            payload["End"] = True

        return payload

    def encode_parallel(self, state) -> Union[dict, List[dict]]:
        from sebs.faas.fsm import State as FsmState

        branches = []
        for branch in state.branches:
            sub_states = {n: FsmState.deserialize(n, s) for n, s in branch.states.items()}
            branch_states = {}
            for sub_state in sub_states.values():
                obj = self.encode_state(sub_state)
                objs = [obj] if isinstance(obj, dict) else obj
                for o in objs:
                    name = o["Name"]
                    branch_states[name] = {k: v for k, v in o.items() if k != "Name"}
            branches.append({"StartAt": branch.root, "States": branch_states})

        payload: Dict[str, Any] = {
            "Name": state.name,
            "Type": "Parallel",
            "Branches": branches,
            # Convert the Parallel output array into a dict keyed by branch root name
            # so downstream states can reference results by name (e.g. $.sifting).
            "ResultSelector": {
                f"{b.root}.$": f"$[{i}]" for i, b in enumerate(state.branches)
            },
            "ResultPath": "$",
        }

        if state.next:
            payload["Next"] = state.next
        else:
            payload["End"] = True

        return payload

    def encode_loop(self, state: Loop) -> Union[dict, List[dict]]:
        map_state = Map(state.name, [state.func_name], state.array, state.name, state.next, None)
        payload = self.encode_map(map_state)
        payload["MaxConcurrency"] = 1
        payload["ResultSelector"] = dict()
        payload["ResultPath"] = "$." + str(uuid.uuid4())[:8]

        return payload

