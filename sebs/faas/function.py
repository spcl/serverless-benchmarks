from abc import ABC
from abc import abstractmethod
from enum import Enum
from typing import List


"""
    Function trigger and implementation of invocation.

    FIXME: implement a generic HTTP invocation and specialize input and output
    processing in classes.
"""


class Trigger(ABC):
    class TriggerType(Enum):
        HTTP = 0
        STORAGE = 1

    @abstractmethod
    def sync_invoke(self):
        pass

    @abstractmethod
    def async_invoke(self):
        pass


"""
    Abstraction base class for FaaS function. Contains a list of associated triggers
    and might implement non-trigger execution if supported by the SDK.
    Example: direct function invocation through AWS boto3 SDK.
"""


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
