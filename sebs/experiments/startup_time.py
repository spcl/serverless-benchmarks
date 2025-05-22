from sebs.experiments.experiment import Experiment
from sebs.experiments.config import Config as ExperimentConfig


class StartupTime(Experiment):
    """
    Experiment to measure function startup time.

    This class currently serves as a placeholder or base for startup time experiments.
    Further implementation would be needed to define the actual measurement logic.
    """
    def __init__(self, config: ExperimentConfig):
        """
        Initialize the StartupTime experiment.

        :param config: Experiment configuration.
        """
        super().__init__(config)

    @staticmethod
    def name() -> str:
        """Return the name of the experiment."""
        return "startup-time"

    @staticmethod
    def typename() -> str:
        """Return the type name of this experiment class."""
        return "Experiment.StartupTime"
