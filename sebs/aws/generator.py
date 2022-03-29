import json
from typing import Dict

from sebs.faas.generator import *

class SFNGenerator(Generator):

    def __init__(self, func_arns: Dict[str, str]):
        super().__init__()
        self._func_arns = func_arns


    def postprocess(self, states: List[State], payloads: List[dict]) -> dict:
        payloads = super().postprocess(states, payloads)
        definition = {
            "Comment": "SeBS auto-generated benchmark",
            "StartAt": states[0].name,
            "States": payloads
        }

        return definition

    def encode_task(self, state: Task) -> dict:
        payload = {
            "Type": "Task",
            "Resource": self._func_arns[state.name]
        }

        if state.next:
            payload["Next"] = state.next
        else:
            payload["End"] = True

        return payload
