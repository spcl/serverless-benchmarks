from abc import ABC
from abc import abstractmethod
from multiprocessing import Semaphore

# from multiprocessing.pool import ThreadPool

from sebs.experiments.config import Config as ExperimentConfig
from sebs.utils import LoggingBase


class Experiment(ABC, LoggingBase):
    def __init__(self, cfg: ExperimentConfig):
        super().__init__()
        self._config = cfg
        self._threads = 1
        self._invocations = 1
        self._invocation_barrier = Semaphore(self._invocations)

    @property
    def config(self):
        return self._config

    @staticmethod
    @abstractmethod
    def name() -> str:
        pass

    @staticmethod
    @abstractmethod
    def typename() -> str:
        pass
