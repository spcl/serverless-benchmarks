import concurrent
import os
import uuid
from typing import TYPE_CHECKING

from sebs.faas.system import System as FaaSSystem
from sebs.experiments.experiment import Experiment
from sebs.experiments.config import Config as ExperimentConfig
from sebs.experiments.result import Result as ExperimentResult
from sebs.utils import serialize

if TYPE_CHECKING:
    from sebs import SeBS


class CommunicationP2P(Experiment):
    def __init__(self, config: ExperimentConfig):
        super().__init__(config)
        self.settings = self.config.experiment_settings(self.name())

    def prepare(self, sebs_client: "SeBS", deployment_client: FaaSSystem):

        # deploy network test function
        from sebs import SeBS  # noqa
        from sebs.faas.function import Trigger

        experiment_type = self.settings["type"]
        self._benchmark = sebs_client.get_benchmark(
            f"051.communication.{experiment_type}", deployment_client, self.config
        )
        self._function = deployment_client.get_function(self._benchmark)

        triggers = self._function.triggers(Trigger.TriggerType.LIBRARY)
        self._trigger = triggers[0]

        self._storage = deployment_client.get_storage(replace_existing=True)
        self._out_dir = os.path.join(sebs_client.output_dir, "communication-p2p", experiment_type)
        if not os.path.exists(self._out_dir):
            os.makedirs(self._out_dir)

        self._experiment_bucket = self._storage.experiments_bucket()

        self._deployment_client = deployment_client

    def run(self):

        for invocations in self.settings["invocations"]["invocations_per_round"]:

            type_name = self.settings["type"]
            deployment_name = self._deployment_client.name()
            experiment_id = f"{deployment_name}-{type_name}-{str(uuid.uuid4())[0:8]}"
            bucket_key = os.path.join(self.name(), experiment_id)
            result = ExperimentResult(self.config, self._deployment_client.config)
            result.begin()

            self.logging.info(
                f"Begin experiment {experiment_id}, with {invocations} invocations per "
                f"function call"
            )

            input_config = {
                "bucket": self._experiment_bucket,
                "key": bucket_key,
                "size": self.settings["size"],
                "invocations": {
                    "warmup": self.settings["invocations"]["warmup"],
                    "invocations": invocations,
                    "with_backoff": False,
                },
            }
            total_iters = self.settings["invocations"]["total"]
            invocations_processed = 0
            iteration = 0

            pool = concurrent.futures.ThreadPoolExecutor()

            while invocations_processed < total_iters:

                self.logging.info(f"Invoking {invocations} repetitions")

                current_input = input_config
                current_input["invocations"]["iteration"] = iteration

                # FIXME: propert implementation in language triggers
                fut = pool.submit(self._trigger.sync_invoke, {**current_input, "role": "producer"})
                consumer = self._trigger.sync_invoke({**current_input, "role": "consumer"})
                result.add_invocation(self._function, consumer)
                result.add_invocation(self._function, fut.result())

                invocations_processed += invocations
                iteration += 1

                self.logging.info(f"Finished {invocations_processed}/{total_iters}")

            result.end()

            results_config = {
                "type": type_name,
                "deployment": deployment_name,
                "benchmark_input": input_config,
                "bucket": self._experiment_bucket,
                "experiment_id": experiment_id,
            }

            file_name = f"invocations_{invocations}_results.json"
            with open(os.path.join(self._out_dir, file_name), "w") as out_f:
                out_f.write(serialize({"experiment": result, "results": results_config}))

    def process(
        self,
        sebs_client: "SeBS",
        deployment_client,
        directory: str,
        logging_filename: str,
    ):
        pass

    @staticmethod
    def name() -> str:
        return "communication-p2p"

    @staticmethod
    def typename() -> str:
        return "Experiment.CommunicationP2P"
