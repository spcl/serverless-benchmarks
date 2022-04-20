import json
from typing import Dict

from sebs.faas.fsm import *

class GCPGenerator(Generator):

    def __init__(self, func_triggers: Dict[str, str]):
        super().__init__()
        self._func_triggers = func_triggers

    def postprocess(self, states: List[State], payloads: List[dict]) -> dict:
        definition = {
            "main" : {
                "params": [
                    "res"
                ],
                "steps": payloads
            }
        }

        return definition

    def encode_task(self, state: Task) -> dict:
        url = self._func_triggers[state.name]

        return {
            state.name: {
                "call": "http.post",
                "args": {
                    "url": url,
                    "body": "${res}"
                },
                "result": "res"
            }
        }

    def encode_switch(self, state: Switch) -> dict:
        return {
            state.name: {
                "switch": [self._encode_case(c) for c in state.cases],
                "next": state.default
            }
        }

    def _encode_case(self, case: Switch.Case) -> dict:
        cond = "res.body." + case.var + " " + case.op + " " + str(case.val)
        return {
            "condition": "${"+cond+"}",
            "next": case.next
        }

