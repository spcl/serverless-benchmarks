"""Provider-neutral finite state machine model for workflow definitions."""

from abc import ABC
from abc import abstractmethod
from typing import Optional, List, Callable, Union, Dict, Type, Any, cast
import json


class State(ABC):
    """Base workflow state with a stable state name."""

    def __init__(self, name: str):
        """Create a named workflow state."""
        self.name = name

    @staticmethod
    def deserialize(name: str, payload: dict) -> "State":
        """Deserialize a state payload into the matching state subclass."""
        cls = _STATE_TYPES[payload["type"]]
        return cls.deserialize(name, payload)


class Task(State):
    """Workflow state that invokes a single function."""

    def __init__(self, name: str, func_name: str, next: Optional[str], failure: Optional[str]):
        """Create a function task state."""
        self.name = name
        self.func_name = func_name
        self.next = next
        self.failure = failure

    @classmethod
    def deserialize(cls, name: str, payload: dict) -> "Task":
        """Deserialize a task state from a definition payload."""
        return cls(
            name=name,
            func_name=payload["func_name"],
            next=payload.get("next"),
            failure=payload.get("failure"),
        )


class Switch(State):
    """Workflow state that chooses the next state from conditions."""

    class Case:
        """Single conditional branch in a switch state."""

        def __init__(self, var: str, op: str, val: str, next: str):
            """Create a switch case."""
            self.var = var
            self.op = op
            self.val = val
            self.next = next

        @staticmethod
        def deserialize(payload: dict) -> "Switch.Case":
            """Deserialize a switch case from a definition payload."""
            return Switch.Case(**payload)

    def __init__(self, name: str, cases: List[Case], default: Optional[str]):
        """Create a switch state."""
        self.name = name
        self.cases = cases
        self.default = default

    @classmethod
    def deserialize(cls, name: str, payload: dict) -> "Switch":
        """Deserialize a switch state from a definition payload."""
        cases = [Switch.Case.deserialize(c) for c in payload["cases"]]

        return cls(name=name, cases=cases, default=payload["default"])


class Branch:
    """A named sub-workflow branch used inside a Parallel state."""

    def __init__(self, root: str, states: Dict[str, dict]):
        """Create a branch with its root state and nested state payloads."""
        self.root = root
        self.states = states

    @staticmethod
    def deserialize(payload) -> "Branch":
        """Deserialize a branch from either legacy or structured payloads."""
        if isinstance(payload, str):
            # Legacy: bare function name — treat as a single-task sub-workflow.
            return Branch(root=payload, states={payload: {"type": "task", "func_name": payload}})
        return Branch(root=payload["root"], states=payload["states"])


class Parallel(State):
    """Workflow state that runs multiple branches concurrently."""

    def __init__(self, name: str, branches: List["Branch"], next: Optional[str]):
        """Create a parallel state."""
        self.name = name
        self.branches = branches
        self.next = next

    @classmethod
    def deserialize(cls, name: str, payload: dict) -> "Parallel":
        """Deserialize a parallel state from a definition payload."""
        branches = [Branch.deserialize(f) for f in payload.get("parallel_functions", [])]
        return cls(name=name, branches=branches, next=payload.get("next"))


class Map(State):
    """Workflow state that maps a nested function or state machine over an array."""

    def __init__(
        self,
        name: str,
        funcs: List,
        array: str,
        root: str,
        next: Optional[str],
        common_params: Optional[List[str]],
    ):
        """Create a map state."""
        self.name = name
        self.funcs = funcs
        self.array = array
        self.root = root
        self.next = next
        self.common_params = common_params

    @classmethod
    def deserialize(cls, name: str, payload: dict) -> "Map":
        """Deserialize a map state from a definition payload."""
        common_params: Optional[List[str]]
        raw = payload.get("common_params")
        if isinstance(raw, str):
            common_params = [p.strip() for p in raw.split(",") if p.strip()]
        else:
            common_params = cast(Optional[List[str]], raw or None)
        return cls(
            name=name,
            funcs=payload["states"],
            array=payload["array"],
            root=payload["root"],
            next=payload.get("next"),
            common_params=common_params,
        )


class Repeat(State):
    """Workflow state that repeats a function a fixed number of times."""

    def __init__(self, name: str, func_name: str, count: int, next: Optional[str]):
        """Create a repeat state."""
        self.name = name
        self.func_name = func_name
        self.count = count
        self.next = next

    @classmethod
    def deserialize(cls, name: str, payload: dict) -> "Repeat":
        """Deserialize a repeat state from a definition payload."""
        return cls(
            name=name,
            func_name=payload["func_name"],
            count=payload["count"],
            next=payload.get("next"),
        )


class Loop(State):
    """Workflow state that loops over an array with a single function."""

    def __init__(self, name: str, func_name: str, array: str, next: Optional[str]):
        """Create a loop state."""
        self.name = name
        self.func_name = func_name
        self.array = array
        self.next = next

    @classmethod
    def deserialize(cls, name: str, payload: dict) -> "Loop":
        """Deserialize a loop state from a definition payload."""
        return cls(
            name=name,
            func_name=payload["func_name"],
            array=payload["array"],
            next=payload.get("next"),
        )


_STATE_TYPES: Dict[str, Type[State]] = {
    "task": Task,
    "switch": Switch,
    "map": Map,
    "repeat": Repeat,
    "loop": Loop,
    "parallel": Parallel,
}


class Generator(ABC):
    """Base class for provider-specific workflow definition generators."""

    def __init__(self, export_func: Callable[[Any], str] = json.dumps):
        """Create a generator with a serialization function."""
        self._export_func = export_func

    def parse(self, path: str):
        """Load and deserialize a workflow definition file."""
        with open(path) as f:
            definition = json.load(f)

        self.states = {n: State.deserialize(n, s) for n, s in definition["states"].items()}
        self.root = self.states[definition["root"]]

    def generate(self) -> str:
        """Generate a provider-specific serialized workflow definition."""
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

    def postprocess(self, payloads: List[dict]) -> Union[dict, List[dict]]:
        """Finalize encoded state payloads before serialization."""
        return payloads

    def encode_state(self, state: State) -> Union[dict, List[dict]]:
        """Dispatch a state object to the matching provider encoder."""
        if isinstance(state, Task):
            return self.encode_task(state)
        elif isinstance(state, Switch):
            return self.encode_switch(state)
        elif isinstance(state, Map):
            return self.encode_map(state)
        elif isinstance(state, Repeat):
            return self.encode_repeat(state)
        elif isinstance(state, Loop):
            return self.encode_loop(state)
        elif isinstance(state, Parallel):
            return self.encode_parallel(state)
        else:
            raise ValueError(f"Unknown state of type {type(state)}.")

    @abstractmethod
    def encode_task(self, state: Task) -> Union[dict, List[dict]]:
        """Encode a task state."""
        pass

    @abstractmethod
    def encode_switch(self, state: Switch) -> Union[dict, List[dict]]:
        """Encode a switch state."""
        pass

    @abstractmethod
    def encode_map(self, state: Map) -> Union[dict, List[dict]]:
        """Encode a map state."""
        pass

    @abstractmethod
    def encode_parallel(self, state: Parallel) -> Union[dict, List[dict]]:
        """Encode a parallel state."""
        pass

    def encode_repeat(self, state: Repeat) -> Union[dict, List[dict]]:
        """Encode a repeat state as a sequence of task states."""
        tasks = []
        for i in range(state.count):
            name = state.name if i == 0 else f"{state.name}_{i}"
            next = state.next if i == state.count - 1 else f"{state.name}_{i+1}"
            task = Task(name, state.func_name, next, None)

            res = self.encode_task(task)
            tasks += res if isinstance(res, list) else [res]

        return tasks

    @abstractmethod
    def encode_loop(self, state: Loop) -> Union[dict, List[dict]]:
        """Encode a loop state."""
        pass
