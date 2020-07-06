from abc import ABC
from abc import abstractmethod
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional

class TriggerType(Enum):
    HTTP = 0
    STORAGE = 1

"""
    Function trigger and implementation of invocation.

    FIXME: implement a generic HTTP invocation and specialize input and output
    processing in classes.
"""


class Trigger(ABC):

    @staticmethod
    @abstractmethod
    def type() -> TriggerType:
        pass

    @abstractmethod
    def sync_invoke(self):
        pass

    @abstractmethod
    def async_invoke(self):
        pass


"""
    Times are reported in microseconds.
"""


class ExecutionTimes:

    client: int
    provider: int
    benchmark: int

    def __init__(self):
        self.client = 0
        self.provider = 0
        self.benchmark = 0


class ExecutionStats:

    memory_used: Optional[float]
    init_time_reported: Optional[int]
    init_time_measured: int
    cold_start: bool
    failure: bool

    def __init__(self):
        self.memory_used = None
        self.init_time_reported = None
        self.init_time_measured = 0
        self.cold_start = False
        self.failure = False


class ExecutionBilling:

    _memory: Optional[int]
    _billed_time: Optional[int]
    _gb_seconds: int

    def __init__(self):
        self.memory = None
        self.billed_time = None
        self.gb_seconds = 0

    @property
    def memory(self) -> Optional[int]:
        return self._memory

    @memory.setter
    def memory(self, val: int):
        self._memory = val

    @property
    def billed_time(self) -> Optional[int]:
        return self._billed_time

    @billed_time.setter
    def billed_time(self, val: int):
        self._billed_time = val

    @property
    def gb_seconds(self) -> int:
        return self._gb_seconds

    @gb_seconds.setter
    def gb_seconds(self, val: int):
        self._gb_seconds = val


class ExecutionResult:

    output: dict
    request_id: str
    times: ExecutionTimes
    stats: ExecutionStats
    billing: ExecutionBilling

    def __init__(self, client_time_begin: datetime, client_time_end: datetime):
        self.output = {}
        self.request_id = ""
        self.times = ExecutionTimes()
        self.times.client = int(
            (client_time_end - client_time_begin) / timedelta(microseconds=1)
        )
        self.stats = ExecutionStats()
        self.billing = ExecutionBilling()

    def parse_benchmark_output(self, output: dict):
        self.output = output
        self.stats.cold_start = self.output["is_cold"]
        self.times.benchmark = int(
            (
                datetime.fromtimestamp(float(self.output["end"]))
                - datetime.fromtimestamp(float(self.output["begin"]))
            )
            / timedelta(microseconds=1)
        )


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

    def sync_invoke(self, payload: dict) -> ExecutionResult:
        raise Exception("Non-trigger invoke not supported!")

    def async_invoke(self, payload: dict) -> ExecutionResult:
        raise Exception("Non-trigger invoke not supported!")
