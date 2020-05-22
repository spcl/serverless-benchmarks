from abc import ABC
from abc import abstractmethod
from enum import Enum
from typing import List


class Trigger(ABC):
    class TriggerType(Enum):
        HTTP = 0
        STORAGE = 1

    @abstractmethod
    def invoke(self):
        pass


class Function:

    _triggers: List[Trigger]

    def __init__(self, name: str):
        self._name = name

    @property
    def name(self):
        return self._name

    def sync_invoke(self, payload: dict):
        raise Exception("Non-trigger invoke not supported!")

    def async_invoke(self, payload: dict):
        raise Exception("Non-trigger invoke not supported!")
