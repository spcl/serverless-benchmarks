import json
import sys
import os

import azure.durable_functions as df

dir_path = os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.join(dir_path, os.path.pardir))

from .fsm import *


def resolve_var(obj, vars: str):
    vars = vars.split(".")
    for var in vars:
        obj = getattr(obj, var)

    return obj


class Executor():

    def __init__(self, path: str, context: df.DurableOrchestrationContext):
        with open(path) as f:
            definition = json.load(f)

        self.states = {n: State.deserialize(n, s)
                       for n, s in definition["states"].items()}
        self.root = self.states[definition["root"]]
        self.context = context
        self.res = None

    def _execute_task(self, state: Task):
        self.res = yield context.call_activity(state.func_name, self.res)

        if state.next:
            next = self.states[state.next]
            self.execute_state(next)

    def _execute_switch(self, state: Switch):
        import operator as op
        ops = {
            "<": op.lt,
            "<=": op.le,
            "==": op.eq,
            ">=": op.ge,
            ">": op.gt
        }

        for case in state.cases:
            var = resolve_var(res, case.var)
            op = ops[case.op]
            if op(var, case.val):
                next = self.states[case.next]
                self.execute_state(next)
                return

        if state.default:
            default = self.state[state.default]
            self.execute_state(default)

    def execute_state(self, state: State):
        funcs = {
            Task: self._execute_task,
            Switch: self._execute_switch,
        }

        func = funcs[type(state)]
        func(state)

    def start_state_machine(self, input):
        self.res = input
        self.execute_state(self.root)
        return self.res


def run_workflow(context: df.DurableOrchestrationContext):
    input = context.get_input()
    executor = Executor("definition.json", context)
    res = executor.start_state_machine(input)

    return res


main = df.Orchestrator.create(run_workflow)