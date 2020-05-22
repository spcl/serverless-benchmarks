from abc import ABC
from abc import abstractmethod

import sebs.benchmark
from .function import Function
from .storage import PersistentStorage


class System(ABC):
    @abstractmethod
    def get_storage(self, replace_existing: bool) -> PersistentStorage:
        pass

    """
        a)  if a cached function is present and no update flag is passed,
            then just return function name
        b)  if a cached function is present and update flag is passed,
            then upload new code
        c)  if no cached function is present, then create code package and
            either create new function on AWS or update an existing one

        :param benchmark:
        :param config: JSON config for benchmark
        :param function_name: Override randomly generated function name
        :return: function name, code size
    """

    @abstractmethod
    def get_function(
        self, code_package: sebs.benchmark.Benchmark, experiment_config: dict
    ) -> Function:
        pass

    @staticmethod
    @abstractmethod
    def name() -> str:
        pass
