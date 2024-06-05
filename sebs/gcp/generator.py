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
        self._map_funcs_steps = dict()

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
                        },
                        "timeout": 900,
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
        id = self._workflow_name + "_" + state.name #+ "_map"
        #not only root function but also remember other map steps.
        self._map_funcs[id] = self._func_triggers[state.root]

        del state.funcs[state.root]
        self._map_funcs_steps[id] = state.funcs
        #self._map_funcs_steps[id] = {state.root : state.funcs}

        res_name = "payload_" + str(uuid.uuid4())[0:8]
        #array = state.name+"_input"
        array = "map_input"
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
                "args": {"workflow_id": id, "arguments": "${"+array+"}", "timeout": 900,},
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

    #payload of branch is passed by name of first function of the branch. 
    def __replace_parallel(self, func, func_name, first_func_name):
        if len(func) == 2:
            #task state
            func[1]["assign_payload_" + func_name]["assign"] = [{func_name : "${" + first_func_name + ".body}"}]
            func[0][func_name]["result"] = first_func_name
        else:
            #it is a map state
            func[3]["assign_payload_" + func_name]["assign"] = [{first_func_name : func[3]["assign_payload_" + first_func_name]["assign"][0][
                func[1][func_name + "_init"]["for"]["in"].replace("$", "").replace("{", "").replace("}", "")
            ]}]
        return func

    def encode_parallel(self, state: Parallel) -> Union[dict, List[dict]]:
        branches = []
        payloads = dict()
        names = dict()

        for i, subworkflow in enumerate(state.funcs):
            states = {n: State.deserialize(n, s) for n, s in subworkflow["states"].items()}
            parallel_funcs = [(self.encode_state(t)) for t in states.values()]
            parallel_funcs_names = [t.name for t in states.values()]
            '''
            for i, func in enumerate(parallel_funcs):
                func_name = parallel_funcs_names[i]
                self.__replace_parallel(func, func_name)
            '''
            #only change assign for last function. 
            self.__replace_parallel(parallel_funcs[-1], parallel_funcs_names[-1], parallel_funcs_names[0])

            names[parallel_funcs_names[0]] = {}

            branch = dict()
            parallel_funcs_simple = []
            for func in parallel_funcs:
                parallel_funcs_simple.append(func[0])
            branch[parallel_funcs_names[0] + "_step"] = { "steps" : parallel_funcs_simple }
            branches.append(branch)
            #branches.append({[parallel_funcs_names[0] + "_step"] : { "steps" : parallel_funcs }})
            payloads[parallel_funcs_names[0]] = "${" + parallel_funcs_names[0] + "}"

        dict_names = [{n : x} for n, x in names.items()]
        #add payload variable such that functions within parallel steps can write to it.
        names["payload"] = ""

        payload = [
            {
            state.name+"_init" : {
                "assign": dict_names
                }
            },
            { 
                state.name : {
                    "parallel": {
                        "shared": [x for x in names.keys()],
                        "branches": [ x for x in branches ]
                    }
                }
            },
            
            {"assign_payload_" + state.name: {"assign": [{"payload": payloads }]}},
        ]
        return payload

    def generate_maps(self):
        #workflows = dict ()
        for workflow_id, url in self._map_funcs.items():
            steps = self._map_funcs_steps[workflow_id]
            states = {n: State.deserialize(n, s) for n, s in steps.items()}
            branch = []
            for t in states.values():
                mystate = self.encode_state(t)
                branch.append(mystate)

            branch = [x for xs in branch for x in xs]
            steps_int = [
                {
                    "map": {
                        "call": "http.post",
                        "args": {
                            "url": url,
                            "body": {
                                "request_id": "${elem.request_id}",
                                "payload": "${elem.payload}"
                            },
                            "timeout": 900,
                        },
                        #"result": "elem"
                        "result": "payload"
                    }
                }
            ]
            if len(branch) != 0:
                steps_int += [{"assign_payload_" + workflow_id: #{"assign": [{"payload": "${payload.body}"}]}}] 
                                                                        {"assign": [{"payload": "${payload.body}"},
                                                                        {"request_id": "${elem.request_id}"}]}}]
                steps_int += branch
                steps_int += [
                    {"ret": {"return": "${payload.body}"}}
                    #{"ret": {"return": "${payload}"}}
                ]
            else:
                steps_int[0]["map"]["result"] = "elem"
                steps_int += [
                    {"ret": {"return": "${elem.body}"}}
                    #{"ret": {"return": "${payload}"}}
                ]
            workflow = {
                        "main": {
                            "params": ["elem"],
                            "steps": steps_int,
                        }
                    }
            
            yield (
                workflow_id,
                self._export_func(workflow)
            )
            

            #workflows[workflow_id] = self._export_func(workflow)
        #return workflows