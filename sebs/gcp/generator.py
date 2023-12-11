import uuid
from typing import Dict, Union, List, Any
import json 

from sebs.faas.fsm import Generator, State, Task, Switch, Map, Repeat, Loop, Parallel


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

        print(json.dumps(definition, default=lambda o: '<not serializable>', indent=2))

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

        payload = [
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
        }, {"assign_payload_" + state.name: {"assign": [{"payload."+state.array: "${"+res_name+"}"}]}}
        ]


        if state.common_params:
            entries = {}
            entries["array_element"] = "${val}"
            entries["request_id"] = "${request_id}"
            params = state.common_params.split(",")
            for param in params:
                entries[param] = "${payload." + param + "}"

            payload[1][state.name+"_init"]["for"]["steps"][0][state.name+"_body"]["assign"][0][tmp]["payload"] = entries
        
        #print(json.dumps(payload, default=lambda o: '<not serializable>', indent=2))
        return payload

        
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

    def encode_parallel(self, state: Parallel) -> Union[dict, List[dict]]:
        states = {n: State.deserialize(n, s) for n, s in state.funcs.items()}
        parallel_funcs = [self.encode_state(t) for t in states.values()]
        parallel_funcs_names = [t.name for t in states.values()]
        #TODO retrieve names: t.name for t in states.values()
        for i, func in enumerate(parallel_funcs):
            func_name = parallel_funcs_names[i]

            #it is a task state
            if len(func) == 2:
                func[1]["assign_payload_" + func_name]["assign"] = [{func_name : "${" + func_name + ".body}"}]
                func[0][func_name]["result"] = func_name
            #it is a map state
            else:
                print("func: ")
                print(json.dumps(func, default=lambda o: '<not serializable>', indent=2))
                print("end func")
                func[3]["assign_payload_" + func_name]["assign"] = [{func_name : func[3]["assign_payload_" + func_name]["assign"][0][
                    func[1][func_name + "_init"]["for"]["in"].replace("$", "").replace("{", "").replace("}", "")
                ]}]

        #FIXME make work for more than two branches. 
        payload = [
            {
            state.name+"_init" : {
                "assign": [
                    {
                    parallel_funcs_names[0] : {}
                    },
                    {
                    parallel_funcs_names[1] : {}
                    }
                ]
                }
            },
            { 
                state.name : {
                    "parallel": {
                        "shared": [x for x in parallel_funcs_names],
                        "branches": [
                            {
                                parallel_funcs_names[0] + "_step" : {
                                    "steps": 
                            #{x for x in parallel_funcs}
                            #FIXME extract from list.
                            parallel_funcs[0]
                            } },
                            {
                                parallel_funcs_names[1] + "_step" : {
                                    "steps": 
                            parallel_funcs[1] 
                            } },
                        ]
                    }
                }
            },
            
            {"assign_payload_" + state.name: {"assign": [{"payload": {parallel_funcs_names[0] : "${" + parallel_funcs_names[0] + "}",
                                                                      parallel_funcs_names[1] : "${" + parallel_funcs_names[1] + "}",
                                                                      }}]}},
        ]
        return payload

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