from sebs.faas.system import System as FaaSSystem
from sebs.experiments import Experiment, ExperimentResult
from sebs.experiments.config import Config as ExperimentConfig
from sebs.utils import serialize


class EvictionModel(Experiment):

    times = [
        1,
        2,
        4,
        8,
        15,
        30,
        60,
        120,
        180,
        240,
        300,
        360,
        480,
        600,
        720,
        900,
        1080,
        1200,
    ]
    function_copies_per_time = 5

    def __init__(self, config: ExperimentConfig):
        super().__init__(config)

    @staticmethod
    def name() -> str:
        return "eviction-model"

    @staticmethod
    def typename() -> str:
        return "Experiment.EvictionModel"

    # def create_function(self, deployment_client

    def prepare(self, sebs_client: "SeBS", deployment_client: FaaSSystem):

        from sebs import Benchmark
        from sebs import SeBS

        self._benchmark = sebs_client.get_benchmark(
            "010.sleep", deployment_client, self.config
        )
        self._deployment_client = deployment_client
        self._result = ExperimentResult(self.config, deployment_client.config)
        name = deployment_client.default_function_name(self._benchmark)
        self.functions_names = [
            f"{name}-{time}-{copy}"
            for time in self.times
            for copy in range(self.function_copies_per_time)
        ]

        for fname in self.functions_names:
            if self._benchmark.functions and fname in self._benchmark.functions:
                # self.logging.info(f"Skip {fname}, exists already.")
                continue
            deployment_client.get_function(self._benchmark, func_name=fname)

    def run(self):

        payload = {"sleep": 1}
        func = self._deployment_client.get_function(
            self._benchmark, self.functions_names[0]
        )
        self._deployment_client.enforce_cold_start(func)
        ret = func.triggers[0].async_invoke(payload)
        result = ret.result()
        print(result.stats.cold_start)
        self._result.add_invocation(func, result)
        print(serialize(self._result))
