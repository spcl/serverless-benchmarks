# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
"""Warm-up experiment: execution time over the first calls to a new container.

perf-cost discards its first calls, so it does not show how a runtime warms up, e.g., while a
JIT compiler optimizes the code. Here, each repetition forces a cold start and keeps the result
of every sequential call that follows.
"""

import csv
import glob
import json
import os
import time
from random import randrange
from typing import Dict, List, Optional, TYPE_CHECKING

from sebs.experiments.experiment import Experiment
from sebs.experiments.result import Result as ExperimentResult
from sebs.faas.function import ExecutionResult, Trigger
from sebs.faas.system import System as FaaSSystem
from sebs.utils import serialize

# import cycle
if TYPE_CHECKING:
    from sebs import SeBS


class WarmUp(Experiment):
    """Warm-up experiment: every call of sequences that start with a cold start.

    Settings (the "warm-up" section of the experiment configuration):
        benchmark: benchmark to run
        input-size: benchmark input size
        repetitions: number of sequences, each starting with a forced cold start
        invocations: number of sequential calls in each sequence
        pause: seconds to wait between calls; optional, default 0
        memory-sizes: memory sizes to run the sequences at; empty for the default size
    """

    @staticmethod
    def name() -> str:
        """Get the name of the experiment.

        Returns:
            The name "warm-up"
        """
        return "warm-up"

    @staticmethod
    def typename() -> str:
        """Get the type name of the experiment.

        Returns:
            The type name "Experiment.WarmUp"
        """
        return "Experiment.WarmUp"

    def prepare(self, sebs_client: "SeBS", deployment_client: FaaSSystem) -> None:
        """Create the benchmark, its input, the function and its HTTP trigger.

        Args:
            sebs_client: The SeBS client to use
            deployment_client: The deployment client to use
        """
        settings = self.config.experiment_settings(self.name())
        self._benchmark = sebs_client.get_benchmark(
            settings["benchmark"], deployment_client, self.config
        )
        self._benchmark_input = self._benchmark.prepare_input(
            deployment_client.system_resources,
            size=settings["input-size"],
            replace_existing=self.config.update_storage,
        )
        self._function = deployment_client.get_function(self._benchmark)

        triggers = self._function.triggers(Trigger.TriggerType.HTTP)
        if len(triggers) == 0:
            self._trigger = deployment_client.create_trigger(
                self._function, Trigger.TriggerType.HTTP
            )
        else:
            self._trigger = triggers[0]

        self._out_dir = os.path.join(sebs_client.output_dir, self.name())
        os.makedirs(self._out_dir, exist_ok=True)

        self._deployment_client = deployment_client
        self._sebs_client = sebs_client

    def run(self) -> None:
        """Run the sequences at each configured memory size."""
        settings = self.config.experiment_settings(self.name())
        memory_sizes = settings.get("memory-sizes", [])

        if len(memory_sizes) == 0:
            self.logging.info("Begin experiment with default memory configuration")
            self._run_memory_size(settings)

        for memory in memory_sizes:
            self.logging.info(f"Begin experiment on memory size {memory}")
            self._function.config.memory = memory
            self._deployment_client.update_function(
                self._function,
                self._benchmark,
                self._benchmark.system_variant,
                (
                    self._benchmark.container_uri
                    if self._benchmark.system_variant.is_container
                    else ""
                ),
            )
            self._sebs_client.cache_client.update_function(self._function)
            self._run_memory_size(settings, suffix=str(memory))

    def _run_memory_size(self, settings: dict, suffix: str = "") -> None:
        """Run all sequences at the current memory size and write their results.

        Args:
            settings: Experiment settings
            suffix: Memory size, used in the output file name
        """
        repetitions = settings["repetitions"]
        invocations = settings["invocations"]
        pause = settings.get("pause", 0)

        # A fresh counter value, so that the first enforced cold start changes the function's
        # configuration even if a previous run left it deployed.
        self._deployment_client.cold_start_counter = randrange(100)

        result = ExperimentResult(self.config, self._deployment_client.config)
        sequences: List[dict] = []
        failures: List[dict] = []
        result.begin()

        for repetition in range(repetitions):
            self._deployment_client.enforce_cold_start([self._function], self._benchmark)
            time.sleep(5)

            calls: List[Optional[str]] = []
            containers: List[str] = []
            first_cold = False
            for call in range(invocations):
                ret = self._invoke(repetition, call, failures)
                if ret is None:
                    calls.append(None)
                else:
                    result.add_invocation(self._function, ret)
                    calls.append(ret.request_id)
                    container = ret.output.get("container_id", "")
                    if container not in containers:
                        containers.append(container)
                    if call == 0:
                        first_cold = bool(ret.stats.cold_start)
                if pause > 0 and call + 1 < invocations:
                    time.sleep(pause)

            if not first_cold:
                self.logging.warning(
                    f"Sequence {repetition + 1}: the first call was not a cold start."
                )
            if len(containers) > 1:
                self.logging.warning(
                    f"Sequence {repetition + 1}: calls reached {len(containers)} containers."
                )
            self.logging.info(
                f"Finished sequence {repetition + 1}/{repetitions} with {invocations} calls."
            )
            sequences.append(
                {
                    "repetition": repetition,
                    "calls": calls,
                    "first_call_cold": first_cold,
                    "containers": containers,
                }
            )

        result.end()

        file_name = (
            f"{self.name()}_results_{suffix}.json" if suffix else f"{self.name()}_results.json"
        )
        with open(os.path.join(self._out_dir, file_name), "w") as out_f:
            out_f.write(
                serialize(
                    {
                        **json.loads(serialize(result)),
                        "sequences": sequences,
                        "statistics": {
                            "failures": failures,
                            "failures_count": len(failures),
                        },
                    }
                )
            )

    def _invoke(
        self, repetition: int, call: int, failures: List[dict]
    ) -> Optional[ExecutionResult]:
        """Invoke the function once, recording a failure instead of raising.

        Args:
            repetition: Index of the sequence
            call: Index of the call within the sequence
            failures: List to append a description of a failed call to

        Returns:
            The execution result, or None if the call failed
        """
        try:
            ret = self._trigger.sync_invoke(self._benchmark_input)
        except Exception as e:
            error = str(e)
        else:
            if not ret.stats.failure:
                return ret
            error = str(ret.output)
        self.logging.error(f"Sequence {repetition + 1}, call {call + 1} failed: {error}")
        failures.append({"repetition": repetition, "call": call, "error": error})
        return None

    def process(
        self,
        sebs_client: "SeBS",
        deployment_client: FaaSSystem,
        directory: str,
        logging_filename: str,
        extend_time_interval: int,
    ) -> None:
        """Download provider metrics and write every call, in order, to `result.csv`.

        The metrics are stored in a `<results>-processed.json` file, which is reused while it
        is newer than its results file.

        Args:
            sebs_client: The SeBS client to use
            deployment_client: The deployment client to use
            directory: Output directory of the experiment run
            logging_filename: Filename for logs
            extend_time_interval: Minutes to extend the metrics query window by on each side
        """
        out_dir = os.path.join(directory, self.name())
        rows: List[dict] = []

        for f in sorted(glob.glob(os.path.join(out_dir, f"{self.name()}_results*.json"))):
            name, extension = os.path.splitext(f)
            if name.endswith("-processed"):
                continue
            processed = f"{name}-processed{extension}"
            # warm-up_results_<memory>.json, or warm-up_results.json for the default size
            parts = os.path.basename(name).split("_")
            memory = int(parts[2]) if len(parts) > 2 else 0

            if os.path.exists(processed) and os.path.getmtime(processed) >= os.path.getmtime(f):
                self.logging.info(f"Using already processed {processed}")
                with open(processed) as in_f:
                    data = json.load(in_f)
                experiments = ExperimentResult.deserialize(
                    data,
                    sebs_client.cache_client,
                    sebs_client.generate_logging_handlers(logging_filename),
                )
            else:
                self.logging.info(f"Processing data in {f}")
                with open(f) as in_f:
                    data = json.load(in_f)
                experiments = ExperimentResult.deserialize(
                    data,
                    sebs_client.cache_client,
                    sebs_client.generate_logging_handlers(logging_filename),
                )
                begin, end = experiments.times()
                if extend_time_interval > 0:
                    begin -= extend_time_interval * 60
                    end += extend_time_interval * 60
                for func in experiments.functions():
                    deployment_client.download_metrics(
                        func,
                        int(begin),
                        int(end),
                        experiments.invocations(func),
                        experiments.metrics(func),
                    )
                with open(processed, "w") as out_f:
                    out_f.write(
                        serialize(
                            {
                                **json.loads(serialize(experiments)),
                                "sequences": data["sequences"],
                                "statistics": data["statistics"],
                            }
                        )
                    )

            invocations: Dict[str, ExecutionResult] = {}
            for func in experiments.functions():
                invocations.update(experiments.invocations(func))
            for sequence in data["sequences"]:
                for call, request_id in enumerate(sequence["calls"]):
                    invoc = invocations.get(request_id) if request_id else None
                    rows.append(self._csv_row(memory, sequence["repetition"], call, invoc))

        measurement_keys = sorted(
            {key for row in rows for key in row if key.startswith("measurement.")}
        )
        columns = [
            "memory",
            "repetition",
            "call",
            "request_id",
            "container_id",
            "is_cold",
            "exec_time",
            "client_time",
            "provider_time",
            "init_time",
            "mem_used",
        ] + measurement_keys
        with open(os.path.join(out_dir, "result.csv"), "w", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=columns, restval="")
            writer.writeheader()
            writer.writerows(rows)
        self.logging.info(f"Wrote {len(rows)} calls to {os.path.join(out_dir, 'result.csv')}")

    @staticmethod
    def _csv_row(memory: int, repetition: int, call: int, invoc: Optional[ExecutionResult]) -> dict:
        """Build one CSV row for a call.

        Args:
            memory: Function memory size in MB, 0 for the default size
            repetition: Index of the sequence
            call: Position of the call in its sequence, 0 for the cold start
            invoc: The call's execution result, None if it failed

        Returns:
            Dictionary from column name to value; a failed call has only its position
        """
        if invoc is None:
            return {"memory": memory, "repetition": repetition, "call": call}
        row = {
            "memory": memory,
            "repetition": repetition,
            "call": call,
            "request_id": invoc.request_id,
            "container_id": invoc.output.get("container_id", ""),
            "is_cold": invoc.stats.cold_start,
            "exec_time": invoc.times.benchmark,
            "client_time": invoc.times.client,
            "provider_time": invoc.provider_times.execution,
            "init_time": invoc.provider_times.initialization,
            "mem_used": invoc.stats.memory_used,
        }
        result = invoc.output.get("result")
        if isinstance(result, dict) and isinstance(result.get("measurement"), dict):
            for key, value in result["measurement"].items():
                row[f"measurement.{key}"] = value
        return row
