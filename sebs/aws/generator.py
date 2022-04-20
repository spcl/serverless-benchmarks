import json
from typing import Dict
import numbers

from sebs.faas.fsm import *

class SFNGenerator(Generator):

    def __init__(self, func_arns: Dict[str, str]):
        super().__init__()
        self._func_arns = func_arns


    def postprocess(self, states: List[State], payloads: List[dict]) -> dict:
        payloads = super().postprocess(states, payloads)
        definition = {
            "Comment": "SeBS auto-generated benchmark",
            "StartAt": self.root.name,
            "States": payloads
        }

        return definition

    def encode_task(self, state: Task) -> dict:
        payload = {
            "Type": "Task",
            "Resource": self._func_arns[state.func_name]
        }

        if state.next:
            payload["Next"] = state.next
        else:
            payload["End"] = True

        return payload

    def encode_switch(self, state: Switch) -> dict:
        choises = [self._encode_case(c) for c in state.cases]
        return {
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
            ">": "GreaterThan"
        }
        cond = type + comp[case.op]

        return {
            "Variable": "$." + case.var,
            cond: case.val,
            "Next": case.next
        }

    def encode_map(self, state: Map) -> dict:
        payload = {
            "Type": "Map",
            "ItemsPath": "$."+state.array,
            "Iterator": {
                "StartAt": "func",
                "States": {
                    "func": {
                        "Type": "Task",
                        "Resource": self._func_arns[state.func_name],
                        "End": True
                    }
                }
            },
            "ResultPath": "$."+state.array
        }

        if state.next:
            payload["Next"] = state.next
        else:
            payload["End"] = True

        if state.max_concurrency:
            payload["MaxConcurrency"] = state.max_concurrency

        return payload