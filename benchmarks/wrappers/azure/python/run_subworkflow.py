import json
import sys
import os
import uuid
import operator
import logging
import datetime

import azure.durable_functions as df
from redis import Redis

dir_path = os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.join(dir_path, os.path.pardir))

from .fsm import *


def get_var(obj, path: str):
    names = path.split(".")
    assert(len(names) > 0)

    for n in names:
        obj = obj[n]

    return obj


def set_var(obj, val, path: str):
    names = path.split(".")
    assert(len(names) > 0)

    for n in names[:-1]:
        obj = obj[n]
    obj[names[-1]] = val

def handler(context: df.DurableOrchestrationContext):
    start = datetime.datetime.now().timestamp()
    ts = start
    now = lambda: datetime.datetime.now().timestamp()
    duration = 0

    input = context.get_input()
    res = input["payload"]
    request_id = input["request_id"]
    all_states = input["states"]
    states = {n: State.deserialize(n, s)
                for n, s in all_states.items()}
    current = states[input["root"]]

    while current:
        logging.info(current.name)

        if isinstance(current, Task):
            input = {"payload": res, "request_id": request_id}

            duration += (now() - ts)
            res = yield context.call_activity(current.func_name, input)
            ts = now()
            current = states.get(current.next, None)
        elif isinstance(current, Switch):
            ops = {
                "<": operator.lt,
                "<=": operator.le,
                "==": operator.eq,
                ">=": operator.ge,
                ">": operator.gt
            }

            next = None
            for case in current.cases:
                var = get_var(res, case.var)
                op = ops[case.op]
                if op(var, case.val):
                    next = states[case.next]
                    break

            if not next and current.default:
                next = states[current.default]
            current = next
        elif isinstance(current, Map):
            array = get_var(res, current.array)
            tasks = []
            if current.common_params:
                #assemble input differently
                for elem in array:
                    #assemble payload
                    payload = {}
                    payload["array_element"] = elem
                    params = current.common_params.split(",")
                    for param in params:
                        payload[param] = get_var(res, param)
                    myinput = {"payload": payload, "request_id": request_id}
                    tasks.append(context.call_activity(current.func_name, myinput))
            else:    
                for elem in array:
                    myinput = {"payload": elem, "request_id": request_id}
                    tasks.append(context.call_activity(current.func_name, myinput))

            duration += (now() - ts)
            map_res = yield context.task_all(tasks)
            ts = now()

            set_var(res, map_res, current.array)
            current = states.get(current.next, None)
        elif isinstance(current, Repeat):
            for i in range(current.count):
                input = {"payload": res, "request_id": request_id}

                duration += (now() - ts)
                res = yield context.call_activity(current.func_name, input)
                ts = now()

            current = states.get(current.next, None)
        elif isinstance(current, Loop):
            array = get_var(res, current.array)
            for elem in array:
                input = {"payload": elem, "request_id": request_id}

                duration += (now() - ts)
                yield context.call_activity(current.func_name, input)
                ts = now()

            current = states.get(current.next, None)

        elif isinstance(current, Parallel):
            parallel_tasks = []
            first_states = []
            state_to_result = {}
            for i, subworkflow in enumerate(current.funcs):
                parallel_states = {n: State.deserialize(n, s) for n, s in subworkflow["states"].items()}

                #for state in parallel_states.values():
                #    state_to_result[state.func_name] = []

                
                first_state = parallel_states[subworkflow["root"]]
                first_states.append(first_state)
                state_to_result[first_state.func_name] = []

                if isinstance(first_state, Task):
                    input = {"payload": res, "request_id": request_id}

                    #task directly here if only one state, task within suborchestrator if multiple states.
                    if first_state.next:
                        #call suborchestrator
                        #FIXME define other parameters. 
                        parallel_task = context.call_sub_orchestrator("run_subworkflow", input, subworkflow["root"], parallel_states)
                        parallel_tasks.append(parallel_task)
                    else:
                        parallel_tasks.append(context.call_activity(first_state.func_name, input))
                    state_to_result[first_state.func_name].append(len(parallel_tasks)-1)
                    
                elif isinstance(first_state, Map):
                    array = get_var(res, first_state.array)
                    tasks = []

                    if first_state.next:
                        #call suborchestrator.
                        if first_state.common_params:
                            #assemble input differently
                            for elem in array:
                                payload = {}
                                payload["array_element"] = elem
                                params = first_state.common_params.split(",")
                                for param in params:
                                    payload[param] = get_var(res, param)
                                myinput = {"payload": payload, "request_id": request_id}
                                #FIXME use right parameters for suborchestrator.
                                parallel_task = context.call_sub_orchestrator("run_subworkflow", myinput, subworkflow["root"], parallel_states)
                                parallel_tasks.append(parallel_task)
                                state_to_result[first_state.func_name].append(len(parallel_tasks)-1)
                        else:    
                            for elem in array:
                                myinput = {"payload": elem, "request_id": request_id}
                                
                                parallel_task = context.call_sub_orchestrator("run_subworkflow", myinput, subworkflow["root"], parallel_states)
                                parallel_tasks.append(parallel_task)
                                state_to_result[first_state.func_name].append(len(parallel_tasks)-1)
                    else: 
                        if first_state.common_params:
                            #assemble input differently
                            for elem in array:
                                payload = {}
                                payload["array_element"] = elem
                                params = first_state.common_params.split(",")
                                for param in params:
                                    payload[param] = get_var(res, param)
                                myinput = {"payload": payload, "request_id": request_id}
                                parallel_tasks.append(context.call_activity(first_state.func_name, myinput))
                                state_to_result[first_state.func_name].append(len(parallel_tasks)-1)
                        else:    
                            for elem in array:
                                myinput = {"payload": elem, "request_id": request_id}
                                parallel_tasks.append(context.call_activity(first_state.func_name, myinput))
                                state_to_result[first_state.func_name].append(len(parallel_tasks)-1)
                    
            duration += (now() - ts)
            map_res = yield context.task_all(parallel_tasks)
            ts = now()
            res = {}

            for state in first_states:
                indices = state_to_result[state.func_name]
                if len(indices) > 1:
                    output = []
                    for index in indices:
                        output.append(map_res[index])
                    res[state.func_name] = output
                else:
                    #task state
                    res[state.func_name] = map_res[indices[0]]

            current = states.get(current.next, None)

        else:
            raise ValueError(f"Undefined state: {current}")

    #workflow_name = os.getenv("APPSETTING_WEBSITE_SITE_NAME")
    func_name = "run_subworkflow"
    
    return res


main = df.Orchestrator.create(handler)
