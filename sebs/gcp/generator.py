import json
from typing import Dict

from sebs.faas.generator import *

class GCPGenerator(Generator):

    def __init__(self, func_triggers: Dict[str, str]):
        super().__init__()
        self._func_triggers = func_triggers

    def postprocess(self, states: List[State], payloads: List[dict]) -> dict:
        definition = {
            "main" : {
                "steps": payloads
            }
        }

        return definition

    def encode_task(self, state: Task) -> dict:
        url = self._func_triggers[state.name]

        return {
            state.name: {
                "call": "http.get",
                "args": {
                    "url": url
                }
            }
        }
