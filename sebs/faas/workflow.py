from abc import abstractmethod
from typing import Callable, Dict, List  # noqa

from sebs.utils import LoggingBase
from .function import Trigger

"""
    Abstraction base class for FaaS function. Contains a list of associated triggers
    and might implement non-trigger execution if supported by the SDK.
    Example: direct function invocation through AWS boto3 SDK.
"""


class Workflow(LoggingBase):
    def __init__(self, benchmark: str, name: str, code_hash: str):
        super().__init__()
        self._benchmark = benchmark
        self._name = name
        self._code_package_hash = code_hash
        self._updated_code = False
        self._triggers: Dict[Trigger.TriggerType, List[Trigger]] = {}

    @property
    def name(self):
        return self._name

    @property
    def benchmark(self):
        return self._benchmark

    @property
    def code_package_hash(self):
        return self._code_package_hash

    @code_package_hash.setter
    def code_package_hash(self, new_hash: str):
        self._code_package_hash = new_hash

    @property
    def updated_code(self) -> bool:
        return self._updated_code

    @updated_code.setter
    def updated_code(self, val: bool):
        self._updated_code = val

    def triggers_all(self) -> List[Trigger]:
        return [trig for trigger_type, triggers in self._triggers.items() for trig in triggers]

    def triggers(self, trigger_type: Trigger.TriggerType) -> List[Trigger]:
        try:
            return self._triggers[trigger_type]
        except KeyError:
            return []

    def add_trigger(self, trigger: Trigger):
        if trigger.trigger_type() not in self._triggers:
            self._triggers[trigger.trigger_type()] = [trigger]
        else:
            self._triggers[trigger.trigger_type()].append(trigger)

    def serialize(self) -> dict:
        return {
            "name": self._name,
            "hash": self._code_package_hash,
            "benchmark": self._benchmark,
            "triggers": [
                obj.serialize() for t_type, triggers in self._triggers.items() for obj in triggers
            ],
        }

    @staticmethod
    @abstractmethod
    def deserialize(cached_config: dict) -> "Workflow":
        pass
