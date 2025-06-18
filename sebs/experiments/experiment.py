"""Base abstract class for implementing serverless benchmark experiments.

This module provides the base Experiment abstract class that defines the common
interface and functionality for all benchmark experiments in the serverless
benchmarking suite. Each experiment type inherits from this class and implements
its specific logic for executing benchmarks, measuring performance, and analyzing
results.

The Experiment class handles:
- Configuration management
- Parallel invocation coordination
- Logging setup
- Type and name identification for experiments
"""

from abc import ABC, abstractmethod
from multiprocessing import Semaphore

# from multiprocessing.pool import ThreadPool

from sebs.experiments.config import Config as ExperimentConfig
from sebs.utils import LoggingBase


class Experiment(ABC, LoggingBase):
    """Abstract base class for all serverless benchmark experiments.
    
    This class provides the common functionality and interface for all
    experiment implementations. It manages configuration, handles logging,
    and defines the abstract methods that must be implemented by specific
    experiment types.
    
    Attributes:
        config: Experiment configuration settings
        _threads: Number of concurrent threads to use for the experiment
        _invocations: Number of function invocations to perform
        _invocation_barrier: Semaphore for coordinating parallel invocations
    """
    
    def __init__(self, cfg: ExperimentConfig):
        """Initialize a new experiment.
        
        Args:
            cfg: Experiment configuration settings
        """
        super().__init__()
        self._config = cfg
        self._threads = 1
        self._invocations = 1
        self._invocation_barrier = Semaphore(self._invocations)

    @property
    def config(self) -> ExperimentConfig:
        """Get the experiment configuration.
        
        Returns:
            The experiment configuration
        """
        return self._config

    @staticmethod
    @abstractmethod
    def name() -> str:
        """Get the name of the experiment.
        
        This method must be implemented by all subclasses to return
        a unique name for the experiment type, which is used for
        configuration and identification.
        
        Returns:
            A string name for the experiment
        """
        pass

    @staticmethod
    @abstractmethod
    def typename() -> str:
        """Get the type name of the experiment.
        
        This method must be implemented by all subclasses to return
        a human-readable type name for the experiment, which is used
        for display and reporting.
        
        Returns:
            A string type name for the experiment
        """
        pass
