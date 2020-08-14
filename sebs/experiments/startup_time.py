from sebs.experiments.experiment import Experiment
from sebs.experiments.config import Config as ExperimentConfig


class StartupTime(Experiment):
    def __init__(self, config: ExperimentConfig):
        super().__init__(config)

    @staticmethod
    def name() -> str:
        return "startup-time"

    @staticmethod
    def typename() -> str:
        return "Experiment.StartupTime"
