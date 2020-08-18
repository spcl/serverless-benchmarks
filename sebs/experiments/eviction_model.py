from sebs.faas.system import System as FaaSSystem
from sebs.experiments.experiment import Experiment
from sebs.experiments.config import Config as ExperimentConfig


class EvictionModel(Experiment):

    #times = [1, 2, 4, 8, 15, 30, 60, 120, 180, 240, 300, 360, 480, 600, 720, 900, 1080, 1200]
    times = [1, 2, 4, 8, 15, 30, 60, 120, 180, 240, 300, 360, 480, 600, 720, 900, 1080, 1200]
    function_copies_per_time = 5


    def __init__(self, config: ExperimentConfig):
        super().__init__(config)

    @staticmethod
    def name() -> str:
        return "eviction-model"

    @staticmethod
    def typename() -> str:
        return "Experiment.EvictionModel"

    #def create_function(self, deployment_client

    def prepare(self, sebs_client: "SeBS", deployment_client: FaaSSystem):

        from sebs import Benchmark
        from sebs import SeBS
        benchmark = sebs_client.get_benchmark(
            "010.sleep",
            deployment_client,
            self.config
        )
        name = deployment_client.default_function_name(benchmark)
        functions_names = [f"{name}-{time}-{copy}" for time in self.times for copy in range(self.function_copies_per_time)]

        for fname in functions_names:
            if benchmark.functions and fname in benchmark.functions:
                self.logging.info(f"Skip {fname}, exists already.")
                continue
            deployment_client.get_function(benchmark, func_name = fname)

