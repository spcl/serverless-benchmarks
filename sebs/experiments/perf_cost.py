import os
from sebs.faas.system import System as FaaSSystem
from sebs.faas.function import Trigger
from sebs.experiments.experiment import Experiment
from sebs.experiments.config import Config as ExperimentConfig


class PerfCost(Experiment):
    def __init__(self, config: ExperimentConfig):
        super().__init__(config)

    @staticmethod
    def name() -> str:
        return "perf-cost"

    @staticmethod
    def typename() -> str:
        return "Experiment.PerfCost"

    def prepare(self, sebs_client: "SeBS", deployment_client: FaaSSystem):

        from sebs import SeBS
        settings = self.config.experiment_settings(self.name())

        self._benchmark = sebs_client.get_benchmark(
            settings["benchmark"], deployment_client, self.config
        )
        self._function = deployment_client.get_function(self._benchmark)

        triggers = self._function.triggers(Trigger.TriggerType.HTTP)
        if len(triggers) == 0:
            self._trigger = deployment_client.create_trigger(
                self._function, Trigger.TriggerType.HTTP
            )
        else:
            self._trigger = triggers[0]

        self._storage = deployment_client.get_storage(replace_existing=True)
        self.benchmark_input = self._benchmark.prepare_input(
            storage=self._storage, size=settings["input-size"]
        )
        self._out_dir = os.path.join(sebs_client.output_dir, "perf-cost")
        if not os.path.exists(self._out_dir):
            os.mkdir(self._out_dir)

    def run(self):
        pass
        #pool = ThreadPool(threads)
        #ports = range(12000, 12000 + invocations)
        #ret = pool.starmap(self.receive_datagrams,
        #   zip(repeat(repetitions, invocations), ports, repeat(ip, invocations))
        #)
        #output_file = os.path.join(self._out_dir, "result.csv")
        #with open(output_file, "w") as csvfile:
        #    writer = csv.writer(csvfile, delimiter=",")
        #    writer.writerow(
        #        [
        #            "memory",
        #            "repetition",
        #            "is_cold",
        #            "client_time",
        #            "connection_time",
        #            "exec_time",
        #            "request_id",
        #        ]
        #    )

    def process(self, directory: str):
        pass
