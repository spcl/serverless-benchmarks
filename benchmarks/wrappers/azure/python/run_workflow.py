import json
import sys
import os
import operator

import azure.durable_functions as df

dir_path = os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.join(dir_path, os.path.pardir))

from .fsm import *


def resolve_var(obj, vars: str):
    vars = vars.split(".")
    for var in vars:
        obj = obj[var]

    return obj


def run_workflow(context: df.DurableOrchestrationContext):
    input = context.get_input()

    with open("definition.json") as f:
        definition = json.load(f)

    states = {n: State.deserialize(n, s)
                   for n, s in definition["states"].items()}
    current = states[definition["root"]]
    res = None

    while current:
        if isinstance(current, Task):
            res = yield context.call_activity(current.func_name, res)
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
                var = resolve_var(res, case.var)
                op = ops[case.op]
                if op(var, case.val):
                    next = states[case.next]
                    break

            if not next and current.default:
                next = states[current.default]
            current = next
        else:
            raise ValueError(f"Undefined state: {current}")

    return res


main = df.Orchestrator.create(run_workflow)