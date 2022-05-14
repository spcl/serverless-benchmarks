import concurrent
import json
import glob
import os
import uuid
from typing import TYPE_CHECKING

import csv

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
        self._out_dir = os.path.join(sebs_client.output_dir, self.name(), experiment_type)
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
                "benchmark": input_config,
                "bucket": self._experiment_bucket,
                "experiment_id": experiment_id,
                "samples": total_iters,
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
        extend_time_interval: int = -1,
    ):
        storage = deployment_client.get_storage(replace_existing=True)

        with open(os.path.join(directory, self.name(), "result.csv"), "w") as csvfile:

            writer = csv.writer(csvfile, delimiter=",")
            writer.writerow(
                [
                    "channel",
                    "size",
                    "invocations-lambda",
                    "value_type",
                    "value",
                ]
            )

            for experiment_type in ["storage"]:

                out_dir = os.path.join(directory, self.name(), experiment_type)
                for f in glob.glob(os.path.join(out_dir, "*.json")):

                    experiment_data = {}
                    with open(f) as fd:
                        experiment_data = json.load(fd)

                    invocations = experiment_data["results"]["benchmark"]["invocations"][
                        "invocations"
                    ]
                    iterations = experiment_data["results"]["benchmark"]["invocations"]["iteration"]
                    bucket_name = experiment_data["results"]["bucket"]
                    bucket_key = experiment_data["results"]["benchmark"]["key"]
                    size = experiment_data["results"]["benchmark"]["size"]

                    results_dir = os.path.join(out_dir, f"results_{invocations}")
                    os.makedirs(results_dir, exist_ok=True)

                    for i in range(iterations + 1):

                        for filename in [
                            "consumer_retries_{}.txt",
                            "producer_times_{}.txt",
                            "producer_retries_{}.txt",
                        ]:

                            bucket_path = "/".join((bucket_key, "results", filename.format(i)))
                            storage.download(
                                bucket_name,
                                bucket_path,
                                os.path.join(results_dir, filename.format(i)),
                            )

                    self.logging.info(
                        f"Downloaded results from storage for {invocations} invocations run."
                    )

                    # Process the downloaded data
                    for i in range(iterations + 1):

                        for filename in [
                            "consumer_retries_{}.txt",
                            "producer_times_{}.txt",
                            "producer_retries_{}.txt",
                        ]:
                            path = os.path.join(results_dir, filename.format(i))

                            data = open(path, "r").read().split()
                            int_data = [int(x) for x in data]
                            for val in int_data[1:]:
                                writer.writerow(
                                    [
                                        experiment_type,
                                        size,
                                        invocations,
                                        filename.split("_{}")[0],
                                        val,
                                    ]
                                )

                    self.logging.info(
                        f"Processed results from storage for {invocations} invocations run."
                    )

    @staticmethod
    def name() -> str:
        return "communication-p2p"

    @staticmethod
    def typename() -> str:
        return "Experiment.CommunicationP2P"
