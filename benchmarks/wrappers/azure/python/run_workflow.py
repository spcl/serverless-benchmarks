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
            parallel_states = {n: State.deserialize(n, s) for n, s in current.funcs.items()}
            
            #parallel_funcs_names = [t.name for t in states.values()]
            state_to_result = {}
            for state in parallel_states.values():
                state_to_result[state.func_name] = []
            #find out what type they have and execute as above?

            parallel_tasks = []
            logging.info("states: ")
            logging.info(parallel_states)
            for state in parallel_states.values():
                if isinstance(state, Task):
                    input = {"payload": res, "request_id": request_id}

                    duration += (now() - ts)
                    parallel_tasks.append(context.call_activity(state.func_name, input))
                    state_to_result[state.func_name].append(len(parallel_tasks)-1)
                    
                elif isinstance(state, Map):
                    logging.info("Map")
                    logging.info(state.func_name)
                    array = get_var(res, state.array)
                    tasks = []
                    if state.common_params:
                        #assemble input differently
                        for elem in array:
                            #assemble payload
                            payload = {}
                            payload["array_element"] = elem
                            params = state.common_params.split(",")
                            for param in params:
                                payload[param] = get_var(res, param)
                            myinput = {"payload": payload, "request_id": request_id}
                            parallel_tasks.append(context.call_activity(state.func_name, myinput))
                            state_to_result[state.func_name].append(len(parallel_tasks)-1)
                    else:    
                        for elem in array:
                            myinput = {"payload": elem, "request_id": request_id}
                            parallel_tasks.append(context.call_activity(state.func_name, myinput))
                            state_to_result[state.func_name].append(len(parallel_tasks)-1)
                
            duration += (now() - ts)
            map_res = yield context.task_all(parallel_tasks)
            ts = now()
            res = {}

            #assemble return payload similarly to other platforms: key is function name, values is its return value.
            for state in parallel_states.values():
                #get respective results of map_res related to func according to state_to_result
                indices = state_to_result[state.func_name]
                logging.info("indices")
                logging.info(indices)
                if len(indices) > 1:
                    output = []
                    for index in indices:
                        output.append(map_res[index])
                    res[state.func_name] = output
                else:
                    #task state
                    res[state.func_name] = map_res[indices[0]]

            logging.info("res: ")
            logging.info(res)

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
