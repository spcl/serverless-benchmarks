import uuid
from typing import Dict, Union, List

from sebs.faas.fsm import Generator, State, Task, Switch, Map, Repeat, Loop


class GCPGenerator(Generator):
    def __init__(self, workflow_name: str, func_triggers: Dict[str, str]):
        super().__init__()
        self._workflow_name = workflow_name
        self._func_triggers = func_triggers
        self._map_funcs: Dict[str, str] = dict()

    def postprocess(self, payloads: List[dict]) -> dict:
        assign_input = {
            "assign_input": {
                "assign": [
                    {"payload": "${input.payload}"},
                    {"request_id": "${input.request_id}"}
                ]
            }
        }
        return_res = {"final": {"return": ["${payload}"]}}

        payloads = [assign_input] + payloads + [return_res]
        definition = {"main": {"params": ["input"], "steps": payloads}}

        return definition

    def encode_task(self, state: Task) -> Union[dict, List[dict]]:
        url = self._func_triggers[state.func_name]

        return [
            {
                state.name: {
                    "call": "http.post",
                    "args": {
                        "url": url,
                        "body": {
                            "request_id": "${request_id}",
                            "payload": "${payload}"
                        }
                    },
                    "result": "payload",
                }
            },
            {"assign_payload_" + state.name: {"assign": [{"payload": "${payload.body}"}]}},
        ]

    def encode_switch(self, state: Switch) -> Union[dict, List[dict]]:
        return {
            state.name: {
                "switch": [self._encode_case(c) for c in state.cases],
                "next": state.default,
            }
        }

    def _encode_case(self, case: Switch.Case) -> dict:
        cond = "payload." + case.var + " " + case.op + " " + str(case.val)
        return {"condition": "${" + cond + "}", "next": case.next}

    def encode_map(self, state: Map) -> Union[dict, List[dict]]:
        id = self._workflow_name + "_" + state.name + "_map"
        self._map_funcs[id] = self._func_triggers[state.func_name]
        res_name = "payload_" + str(uuid.uuid4())[0:8]
        array = state.name+"_input"
        tmp = "tmp_" + str(uuid.uuid4())[0:8]

        return [
        {
            state.name+"_init_empty": {
                "assign": [
                    {array: "${[]}"}
                ]
            }
        },
        {
            state.name+"_init": {
                "for": {
                    "value": "val",
                    "in": "${payload." + state.array + "}",
                    "steps": [
                        {
                            state.name+"_body": {
                                "assign": [
                                    {tmp: {"payload": "${val}", "request_id": "${request_id}"}},
                                    {array: "${list.concat("+array+", "+tmp+")}"}
                                ]
                            }
                        }
                    ]
                }
            }
        },
        {
            state.name: {
                "call": "experimental.executions.map",
                "args": {"workflow_id": id, "arguments": "${"+array+"}"},
                "result": res_name,
            }
        }, {"assign_payload_" + state.name: {"assign": [{"payload."+state.array: "${"+res_name+"}"}]}}]

    def encode_loop(self, state: Loop) -> Union[dict, List[dict]]:
        url = self._func_triggers[state.func_name]

        return {
            state.name: {
                "for": {
                    "value": "val",
                    "index": "idx",
                    "in": "${payload."+state.array+"}",
                    "steps": [
                        {
                            state.name+"_body": {
                                "call": "http.post",
                                "args": {
                                    "url": url,
                                    "body": {
                                        "request_id": "${request_id}",
                                        "payload": "${val}"
                                    }
                                }
                            }
                        }
                    ]
                }
            }
        }

    def generate_maps(self):
        for workflow_id, url in self._map_funcs.items():
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
                                            "body": {
                                                "request_id": "${elem.request_id}",
                                                "payload": "${elem.payload}"
                                            }
                                        },
                                        "result": "elem"
                                    }
                                },
                                {"ret": {"return": "${elem.body}"}}
                            ],
                        }
                    }
                ),
            )
