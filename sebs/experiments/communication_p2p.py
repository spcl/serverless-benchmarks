from __future__ import annotations

import concurrent
import json
import glob
import os
import uuid
from enum import Enum
from typing import TYPE_CHECKING

import csv

from sebs.faas.config import Resources
from sebs.faas.system import System as FaaSSystem
from sebs.experiments.experiment import Experiment
from sebs.experiments.config import Config as ExperimentConfig
from sebs.experiments.result import Result as ExperimentResult
from sebs.utils import serialize

if TYPE_CHECKING:
    from sebs import SeBS


class CommunicationP2P(Experiment):
    class Type(str, Enum):
        STORAGE = ("storage",)
        KEY_VALUE = "key-value"
        REDIS = "redis"

        @staticmethod
        def deserialize(val: str) -> CommunicationP2P.Type:
            for member in CommunicationP2P.Type:
                if member.value == val:
                    return member
            raise Exception(f"Unknown experiment type {val}")

    def __init__(self, config: ExperimentConfig):
        super().__init__(config)
        self.settings = self.config.experiment_settings(self.name())
        self.benchmarks = {
            CommunicationP2P.Type.STORAGE: "051.communication.storage",
            CommunicationP2P.Type.KEY_VALUE: "052.communication.key-value",
            CommunicationP2P.Type.REDIS: "053.communication.redis",
        }

    def prepare(self, sebs_client: "SeBS", deployment_client: FaaSSystem):

        # deploy network test function
        from sebs import SeBS  # noqa
        from sebs.faas.function import Trigger

        experiment_type = CommunicationP2P.Type.deserialize(self.settings["type"])
        benchmark_name = self.benchmarks.get(experiment_type)
        assert benchmark_name is not None
        self._benchmark = sebs_client.get_benchmark(benchmark_name, deployment_client, self.config)
        self._function = deployment_client.get_function(self._benchmark)

        triggers = self._function.triggers(Trigger.TriggerType.LIBRARY)
        self._trigger = triggers[0]

        self._storage = deployment_client.get_storage(replace_existing=True)
        self._out_dir = os.path.join(sebs_client.output_dir, self.name(), experiment_type)
        if not os.path.exists(self._out_dir):
            os.makedirs(self._out_dir)

        self._experiment_bucket = self._storage.experiments_bucket()
        self._deployment_client = deployment_client

        if experiment_type == CommunicationP2P.Type.KEY_VALUE:

            self._table_name = deployment_client.config.resources.get_key_value_table(
                Resources.StorageType.EXPERIMENTS
            )
            self.logging.info(f"Using key-value storage with table {self._table_name}")

    def run(self):

        for invocations in self.settings["invocations"]["invocations_per_round"]:

            type_name = self.settings["type"]
            deployment_name = self._deployment_client.name()
            experiment_id = f"{deployment_name}-{type_name}-{str(uuid.uuid4())[0:8]}"
            bucket_key = os.path.join(self.name(), experiment_id)
            result = ExperimentResult(self.config, self._deployment_client.config)
            result.begin()

            input_config = {
                "bucket": self._experiment_bucket,
                "key": bucket_key,
                "invocations": {
                    "warmup": self.settings["invocations"]["warmup"],
                    "invocations": invocations,
                    "with_backoff": False,
                },
            }
            self._additional_settings(type_name, input_config)

            for size in self.settings["sizes"]:

                self.logging.info(
                    f"Begin experiment {experiment_id}, with {size} size, with {invocations} "
                    f" invocations per function call."
                )

                input_config["size"] = size
                total_iters = self.settings["invocations"]["total"]
                invocations_processed = 0
                iteration = 0
                offset = 0
                errors = 0
                max_retries = 3

                pool = concurrent.futures.ThreadPoolExecutor(2)

                while invocations_processed < total_iters:

                    self.logging.info(
                        f"Invoking {invocations} repetitions, message offset {offset}."
                    )

                    current_input = input_config
                    current_input["invocations"]["iteration"] = iteration
                    current_input["invocations"]["offset"] = offset

                    # FIXME: propert implementation in language triggers
                    fut = pool.submit(
                        self._trigger.sync_invoke, {**current_input, "role": "producer"}
                    )
                    consumer = self._trigger.sync_invoke({**current_input, "role": "consumer"})
                    producer = fut.result()

                    if consumer.stats.failure or producer.stats.failure:
                        self.logging.info("One of invocations failed, repeating!")
                        # update offset to NOT reuse messages
                        offset += self.settings["invocations"]["warmup"] + invocations
                        errors += 1

                        if errors >= max_retries:
                            self.logging.error("More than three failed invocations, giving up!")
                            raise RuntimeError()

                        continue
                    else:
                        errors += 1

                    result.add_invocation(self._function, consumer)
                    result.add_invocation(self._function, producer)

                    invocations_processed += invocations
                    iteration += 1
                    offset += self.settings["invocations"]["warmup"] + invocations

                    self.logging.info(f"Finished {invocations_processed}/{total_iters}")

            result.end()

            results_config = {
                "type": type_name,
                "deployment": deployment_name,
                "benchmark": input_config,
                "bucket": self._experiment_bucket,
                "experiment_id": experiment_id,
                "samples": total_iters,
                "sizes": self.settings["sizes"],
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

        files_to_read = [
            "consumer_retries_{}_{}.txt",
            "producer_times_{}_{}.txt",
            "producer_retries_{}_{}.txt",
        ]
        additional_files = {
            CommunicationP2P.Type.KEY_VALUE: [
                "producer_write_units_{}_{}.txt",
                "producer_read_units_{}_{}.txt",
                "consumer_write_units_{}_{}.txt",
                "consumer_read_units_{}_{}.txt",
            ]
        }

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

            for experiment_type in [
                CommunicationP2P.Type.STORAGE,
                CommunicationP2P.Type.KEY_VALUE,
                CommunicationP2P.Type.REDIS,
            ]:

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
                    sizes = experiment_data["results"]["sizes"]

                    results_dir = os.path.join(out_dir, f"results_{invocations}")
                    os.makedirs(results_dir, exist_ok=True)

                    for size in sizes:

                        for i in range(iterations + 1):

                            for filename in [
                                *files_to_read,
                                *additional_files.get(experiment_type, []),
                            ]:

                                bucket_path = "/".join(
                                    (bucket_key, "results", filename.format(size, i))
                                )
                                storage.download(
                                    bucket_name,
                                    bucket_path,
                                    os.path.join(results_dir, filename.format(size, i)),
                                )

                        self.logging.info(
                            f"Downloaded results from storage for {size} size, "
                            f"{invocations} invocations run."
                        )

                        # Process the downloaded data
                        for i in range(iterations + 1):

                            for filename in [
                                *files_to_read,
                                *additional_files.get(experiment_type, []),
                            ]:

                                path = os.path.join(results_dir, filename.format(size, i))

                                data = open(path, "r").read().split()
                                double_data = [float(x) for x in data]
                                for val in double_data[1:]:
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
                            f"Processed results from storage for {size} size, "
                            f"{invocations} invocations run."
                        )

    def _additional_settings(self, experiment_type: CommunicationP2P.Type, config: dict):

        if experiment_type == CommunicationP2P.Type.REDIS:
            config["redis"] = self.settings["redis"]

    @staticmethod
    def name() -> str:
        return "communication-p2p"

    @staticmethod
    def typename() -> str:
        return "Experiment.CommunicationP2P"
