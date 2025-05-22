from abc import ABC
from abc import abstractmethod
from multiprocessing import Semaphore

# from multiprocessing.pool import ThreadPool

from sebs.experiments.config import Config as ExperimentConfig
from sebs.utils import LoggingBase


class Experiment(ABC, LoggingBase):
    """
    Abstract base class for all SeBS experiments.

    Provides a common structure and configuration handling for experiments.
    Subclasses must implement the `name` and `typename` static methods.
    """
    def __init__(self, cfg: ExperimentConfig):
        """
        Initialize a new Experiment.

        :param cfg: Experiment configuration object.
        """
        super().__init__()
        self._config = cfg
        self._threads = 1
        self._invocations = 1
        self._invocation_barrier = Semaphore(self._invocations)

    @property
    def config(self) -> ExperimentConfig:
        """The configuration object for this experiment."""
        return self._config

    @staticmethod
    @abstractmethod
    def name() -> str:
        """
        Return the a short, human-readable name of the experiment.
        This name is used to identify the experiment in configurations and results.

        :return: The name of the experiment.
        """
        pass

    @staticmethod
    @abstractmethod
    def typename() -> str:
        """
        Return the type name of the experiment class for serialization and deserialization.
        Typically in the format "Experiment.ClassName".

        :return: The type name of the experiment class.
        """
        pass
