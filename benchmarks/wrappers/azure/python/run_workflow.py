import json
import sys
import os
import operator
import logging
import copy

import azure.durable_functions as df

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


def child_instance_id(parent_instance_id: str, state_name: str, index: int, ordinal: int):
    safe_state = "".join(c if c.isalnum() or c in "-_" else "-" for c in state_name)
    return f"{parent_instance_id}-{ordinal}-{safe_state}-{index}"


def handler(context: df.DurableOrchestrationContext):
    with open("definition.json") as f:
        definition = json.load(f)

    states = {n: State.deserialize(n, s)
                   for n, s in definition["states"].items()}
    current = states[definition["root"]]
    input = context.get_input()

    logging.info("START")
    res = input["payload"]
    request_id = input["request_id"]
    parent_instance_id = getattr(context, "instance_id", request_id)
    child_ordinal = 0

    while current:
        logging.info(current.name)

        if isinstance(current, Task):
            input = {"payload": res, "request_id": request_id}

            if current.failure is None:
                res = yield context.call_activity(current.func_name, input)
                current = states.get(current.next, None)
            else:
                try:
                    res = yield context.call_activity(current.func_name, input)
                    current = states.get(current.next, None)
                except:
                    current = states.get(current.failure, None)

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
                    for idx, elem in enumerate(array):
                        payload = {}
                        payload["array_element"] = elem
                        params = current.common_params.split(",")
                        for param in params:
                            payload[param] = get_var(res, param)
                        myinput = {"payload": payload, "request_id": request_id}
                        myinput["root"] = current.root

                        myinput["states"] = current.funcs
                        instance_id = child_instance_id(
                            parent_instance_id, current.name, idx, child_ordinal
                        )
                        child_ordinal += 1
                        parallel_task = context.call_sub_orchestrator(
                            "run_subworkflow",
                            myinput,
                            instance_id,
                        )
                        tasks.append(parallel_task)
                else:    
                    for idx, elem in enumerate(array):
                        myinput = {"payload": elem, "request_id": request_id}
                        myinput["root"] = current.root
                        myinput["states"] = current.funcs
                        
                        instance_id = child_instance_id(
                            parent_instance_id, current.name, idx, child_ordinal
                        )
                        child_ordinal += 1
                        parallel_task = context.call_sub_orchestrator(
                            "run_subworkflow",
                            myinput,
                            instance_id,
                        )
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

            map_res = yield context.task_all(tasks)

            set_var(res, map_res, current.array)
            current = states.get(current.next, None)
        elif isinstance(current, Repeat):
            for i in range(current.count):
                input = {"payload": res, "request_id": request_id}

                res = yield context.call_activity(current.func_name, input)

            current = states.get(current.next, None)
        elif isinstance(current, Loop):
            array = get_var(res, current.array)
            for elem in array:
                input = {"payload": elem, "request_id": request_id}

                yield context.call_activity(current.func_name, input)

            current = states.get(current.next, None)

        elif isinstance(current, Parallel):
            parallel_tasks = []
            first_states = []
            state_to_result = {}
            for i, subworkflow in enumerate(current.funcs):
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
                        instance_id = child_instance_id(
                            parent_instance_id, f"{current.name}-{i}", 0, child_ordinal
                        )
                        child_ordinal += 1
                        parallel_task = context.call_sub_orchestrator(
                            "run_subworkflow",
                            input,
                            instance_id,
                        )
                        parallel_tasks.append(parallel_task)
                    else:
                        parallel_tasks.append(context.call_activity(first_state.func_name, input))
                    state_to_result[first_state.func_name].append(len(parallel_tasks)-1)
                    
                elif isinstance(first_state, Map):
                    array = get_var(res, first_state.array)

                    if first_state.next:
                        #call suborchestrator.
                        if first_state.common_params:
                            #assemble input differently
                            for elem_idx, elem in enumerate(array):
                                payload = {}
                                payload["array_element"] = elem
                                params = first_state.common_params.split(",")
                                for param in params:
                                    payload[param] = get_var(res, param)
                                myinput = {"payload": payload, "request_id": request_id}
                                myinput["root"] = subworkflow["root"]
                                myinput["states"] = subworkflow["states"]
                                instance_id = child_instance_id(
                                    parent_instance_id,
                                    f"{current.name}-{i}",
                                    elem_idx,
                                    child_ordinal,
                                )
                                child_ordinal += 1
                                parallel_task = context.call_sub_orchestrator(
                                    "run_subworkflow",
                                    myinput,
                                    instance_id,
                                )
                                parallel_tasks.append(parallel_task)
                                state_to_result[first_state.func_name].append(len(parallel_tasks)-1)
                        else:    
                            for elem_idx, elem in enumerate(array):
                                myinput = {"payload": elem, "request_id": request_id}
                                
                                myinput["root"] = subworkflow["root"]
                                myinput["states"] = subworkflow["states"]
                                instance_id = child_instance_id(
                                    parent_instance_id,
                                    f"{current.name}-{i}",
                                    elem_idx,
                                    child_ordinal,
                                )
                                child_ordinal += 1
                                parallel_task = context.call_sub_orchestrator(
                                    "run_subworkflow",
                                    myinput,
                                    instance_id,
                                )
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
                    
            map_res = yield context.task_all(parallel_tasks)
            base_res = res
            res = {}

            for state in first_states:
                #get respective results of map_res related to func according to state_to_result
                indices = state_to_result[state.func_name]
                if len(indices) > 1:
                    output = []
                    for index in indices:
                        output.append(map_res[index])
                    if isinstance(state, Map):
                        branch_res = copy.deepcopy(base_res)
                        set_var(branch_res, output, state.array)
                        res[state.func_name] = branch_res
                    else:
                        res[state.func_name] = output
                else:
                    #task state
                    output = map_res[indices[0]]
                    if isinstance(state, Map):
                        branch_res = copy.deepcopy(base_res)
                        set_var(branch_res, output, state.array)
                        res[state.func_name] = branch_res
                    else:
                        res[state.func_name] = output

            current = states.get(current.next, None)

        else:
            raise ValueError(f"Undefined state: {current}")

    return res


main = df.Orchestrator.create(handler)
