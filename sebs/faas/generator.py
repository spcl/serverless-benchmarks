from abc import ABC
from abc import abstractmethod
from typing import Optional, List, Callable
from enum import Enum
import json


class State(ABC):

    def __init__(self, name: str):
        self.name = name

    @staticmethod
    def deserialize(payload: dict) -> "State":
        cls = _STATE_TYPES[payload["type"]]
        return cls.deserialize(payload)


class Task(State):

    def __init__(self, name: str, func_name: str, next: Optional[str], parameters: Optional[List[str]]):
        self.name = name
        self.func_name = func_name
        self.next = next
        self.parameters = parameters

    @staticmethod
    def deserialize(payload: dict) -> State:
        return Task(
            name=payload["name"],
            func_name=payload["func_name"],
            next=payload.get("next"),
            parameters=payload.get("parameters")
        )


# class Switch(State):
#
#     class Operator(Enum):
#         less = "less"
#         less_equal = "less_equal"
#         equal = "equal"
#         greater_equal = "greater_equal"
#         greater = "greater"
#
#     class ConditionType(Enum):
#         numeric = "numeric"
#         string = "string"
#
#     class Condition:
#         pass
#
#     def __init__(self, name: str, condition: Condition, condition_type: ConditionType):
#         self.name = name
#         self.condition = condition
#         self.condition_type = condition_type
#
#     @staticmethod
#     def deserialize(payload: dict) -> Switch:
#         return Switch(
#             payload["name"],
#             payload["condition"],
#             payload["condition_type"]
#         )


_STATE_TYPES = {
    "task": Task
}


class Generator(ABC):

    def __init__(self):
        self._states: List[State] = []

    def parse(self, path: str):
        with open(path) as f:
            states = json.load(f)

        self._states = [State.deserialize(s) for s in states]

        if len(states) == 0:
            raise RuntimeError("A workflow definition must have at least one state.")

    def generate(self) -> str:
        payloads = [self.encode_state(s) for s in self._states]
        definition = self.postprocess(self._states, payloads)

        return json.dumps(definition)

    def postprocess(self, states: List[State], payloads: List[dict]) -> dict:
        return {s.name: p for (s, p) in zip(states, payloads)}

    def encode_state(self, state: State) -> dict:
        if isinstance(state, Task):
            return self.encode_task(state)

    @abstractmethod
    def encode_task(self, state: Task) -> dict:
        pass