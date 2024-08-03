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

    with open("definition.json") as f:
        definition = json.load(f)

    states = {n: State.deserialize(n, s)
                   for n, s in definition["states"].items()}
    current = states[definition["root"]]
    input = context.get_input()

    logging.info("START")
    res = input["payload"]
    request_id = input["request_id"]

    while current:
        logging.info(current.name)

        if isinstance(current, Task):
            input = {"payload": res, "request_id": request_id}

            duration += (now() - ts)

            if current.failure is None:
                res = yield context.call_activity(current.func_name, input)
                current = states.get(current.next, None)
            else:
                try:
                    res = yield context.call_activity(current.func_name, input)
                    current = states.get(current.next, None)
                except:
                    current = states.get(current.failure, None)

            ts = now()

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

            map_states = {n: State.deserialize(n, s) for n, s in current.funcs.items()}
            first_state = map_states[current.root]

            array = get_var(res, current.array)
            tasks = []
            if first_state.next:
                #call suborchestrator - each map task should proceed with next step directly after it finished.
                if current.common_params:
                    for elem in array:
                        payload = {}
                        payload["array_element"] = elem
                        params = current.common_params.split(",")
                        for param in params:
                            payload[param] = get_var(res, param)
                        myinput = {"payload": payload, "request_id": request_id}
                        myinput["root"] = current.root

                        myinput["states"] = current.funcs
                        uuid_name = str(uuid.uuid4())[0:4]
                        parallel_task = context.call_sub_orchestrator("run_subworkflow", myinput, uuid_name)
                        tasks.append(parallel_task)
                else:    
                    for elem in array:
                        myinput = {"payload": elem, "request_id": request_id}
                        myinput["root"] = current.root
                        myinput["states"] = current.funcs
                        
                        uuid_name = str(uuid.uuid4())[0:4]
                        parallel_task = context.call_sub_orchestrator("run_subworkflow", myinput, uuid_name)
                        tasks.append(parallel_task)
            else:
                if current.common_params:
                    #assemble input differently
                    for elem in array:
                        payload = {}
                        payload["array_element"] = elem
                        params = current.common_params.split(",")
                        for param in params:
                            payload[param] = get_var(res, param)
                        myinput = {"payload": payload, "request_id": request_id}
                        tasks.append(context.call_activity(first_state.func_name, myinput))
                else:    
                    for elem in array:
                        myinput = {"payload": elem, "request_id": request_id}
                        tasks.append(context.call_activity(first_state.func_name, myinput))

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
            for subworkflow in current.funcs:
                parallel_states = {n: State.deserialize(n, s) for n, s in subworkflow["states"].items()}
                
                first_state = parallel_states[subworkflow["root"]]
                first_states.append(first_state)
                state_to_result[first_state.func_name] = []

                if isinstance(first_state, Task):                    
                    input = {"payload": res, "request_id": request_id}

                    #task directly here if only one state, task within suborchestrator if multiple states.
                    if first_state.next:
                        input["root"] = subworkflow["root"]
                        input["states"] = subworkflow["states"] #parallel_states
                        parallel_task = context.call_sub_orchestrator("run_subworkflow", input)
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
                                myinput["root"] = subworkflow["root"]
                                myinput["states"] = subworkflow["states"]
                                parallel_task = context.call_sub_orchestrator("run_subworkflow", myinput)
                                parallel_tasks.append(parallel_task)
                                state_to_result[first_state.func_name].append(len(parallel_tasks)-1)
                        else:    
                            for elem in array:
                                myinput = {"payload": elem, "request_id": request_id}
                                
                                myinput["root"] = subworkflow["root"]
                                myinput["states"] = subworkflow["states"]
                                parallel_task = context.call_sub_orchestrator("run_subworkflow", myinput)
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
                #get respective results of map_res related to func according to state_to_result
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

    workflow_name = os.getenv("APPSETTING_WEBSITE_SITE_NAME")
    func_name = "run_workflow"

    payload = {
        "func": func_name,
        "start": start,
        "end": start+duration
    }

    payload = json.dumps(payload)

    redis = Redis(host={{REDIS_HOST}},
          port=6379,
          decode_responses=True,
          socket_connect_timeout=10,
          password={{REDIS_PASSWORD}})

    key = os.path.join(workflow_name, func_name, request_id, str(uuid.uuid4())[0:8])
    redis.set(key, payload)

    return res


main = df.Orchestrator.create(handler)
