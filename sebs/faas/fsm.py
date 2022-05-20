from abc import ABC
from abc import abstractmethod
from typing import Optional, List, Callable, Union, Dict, Type, Tuple
import json


class State(ABC):
    def __init__(self, name: str):
        self.name = name

    @staticmethod
    def deserialize(name: str, payload: dict) -> "State":
        cls = _STATE_TYPES[payload["type"]]
        return cls.deserialize(name, payload)


class Task(State):
    def __init__(self, name: str, func_name: str, next: Optional[str]):
        self.name = name
        self.func_name = func_name
        self.next = next

    @classmethod
    def deserialize(cls, name: str, payload: dict) -> "Task":
        return cls(name=name, func_name=payload["func_name"], next=payload.get("next"))


class Switch(State):
    class Case:
        def __init__(self, var: str, op: str, val: str, next: str):
            self.var = var
            self.op = op
            self.val = val
            self.next = next

        @staticmethod
        def deserialize(payload: dict) -> "Switch.Case":
            return Switch.Case(**payload)

    def __init__(self, name: str, cases: List[Case], default: Optional[str]):
        self.name = name
        self.cases = cases
        self.default = default

    @classmethod
    def deserialize(cls, name: str, payload: dict) -> "Switch":
        cases = [Switch.Case.deserialize(c) for c in payload["cases"]]

        return cls(name=name, cases=cases, default=payload["default"])


class Map(State):
    def __init__(self, name: str, func_name: str, array: str, next: Optional[str]):
        self.name = name
        self.func_name = func_name
        self.array = array
        self.next = next

    @classmethod
    def deserialize(cls, name: str, payload: dict) -> "Map":
        return cls(
            name=name,
            func_name=payload["func_name"],
            array=payload["array"],
            next=payload.get("next"),
        )


class Repeat(State):
    def __init__(self, name: str, func_name: str, count: int, next: Optional[str]):
        self.name = name
        self.func_name = func_name
        self.count = count
        self.next = next

    @classmethod
    def deserialize(cls, name: str, payload: dict) -> "Task":
        return cls(name=name, func_name=payload["func_name"], count=payload["count"], next=payload.get("next"))


_STATE_TYPES: Dict[str, Type[State]] = {"task": Task, "switch": Switch, "map": Map, "repeat": Repeat}


class Generator(ABC):
    def __init__(self, export_func: Callable[[dict], str] = json.dumps):
        self._export_func = export_func

    def parse(self, path: str):
        with open(path) as f:
            definition = json.load(f)

        self.states = {n: State.deserialize(n, s) for n, s in definition["states"].items()}
        self.root = self.states[definition["root"]]

    def generate(self) -> str:
        states = list(self.states.values())
        payloads = []
        for s in states:
            obj = self.encode_state(s)
            if isinstance(obj, dict):
                payloads.append(obj)
            elif isinstance(obj, list):
                payloads += obj
            else:
                raise ValueError("Unknown encoded state returned.")

        definition = self.postprocess(payloads)

        return self._export_func(definition)

    def postprocess(self, payloads: List[dict]) -> dict:
        return payloads

    def encode_state(self, state: State) -> Union[dict, List[dict]]:
        if isinstance(state, Task):
            return self.encode_task(state)
        elif isinstance(state, Switch):
            return self.encode_switch(state)
        elif isinstance(state, Map):
            return self.encode_map(state)
        elif isinstance(state, Repeat):
            return self.encode_repeat(state)
        else:
            raise ValueError(f"Unknown state of type {type(state)}.")

    @abstractmethod
    def encode_task(self, state: Task) -> Union[dict, List[dict]]:
        pass

    @abstractmethod
    def encode_switch(self, state: Switch) -> Union[dict, List[dict]]:
        pass

    @abstractmethod
    def encode_map(self, state: Map) -> Union[dict, List[dict]]:
        pass

    def encode_repeat(self, state: Repeat) -> Union[dict, List[dict]]:
        tasks = []
        for i in range(state.count):
            name = state.name if i == 0 else f"{state.name}_{i}"
            next = state.next if i == state.count - 1 else f"{state.name}_{i+1}"
            task = Task(name, state.func_name, next)

            res = self.encode_task(task)
            tasks += res if isinstance(res, list) else [res]

        return tasks
