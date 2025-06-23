"""Performance and cost measurement experiment implementation.

This module provides the PerfCost experiment implementation, which measures
the performance characteristics and execution costs of serverless functions.
It can run several experiment types:

- Cold: Measures cold start performance by enforcing container recreation
- Warm: Measures warm execution performance with reused containers
- Burst: Measures performance under concurrent burst load
- Sequential: Measures performance with sequential invocations

The experiment collects detailed metrics about execution time, memory usage,
and costs, and provides statistical analysis of the results.
"""

import json
import os
import time
from enum import Enum
from multiprocessing.pool import ThreadPool
from typing import List, TYPE_CHECKING

from sebs.faas.system import System as FaaSSystem
from sebs.faas.function import Trigger
from sebs.experiments.experiment import Experiment
from sebs.experiments.result import Result as ExperimentResult
from sebs.experiments.config import Config as ExperimentConfig
from sebs.utils import serialize
from sebs.statistics import basic_stats, ci_tstudents, ci_le_boudec

# import cycle
if TYPE_CHECKING:
    from sebs import SeBS


class PerfCost(Experiment):
    """Performance and cost measurement experiment.

    This experiment measures the performance characteristics and execution
    costs of serverless functions under different execution conditions.
    It can measure cold starts, warm execution, burst load, and sequential
    execution patterns.

    The experiment can be configured to run with different memory sizes,
    allowing for comparison of performance across different resource allocations.

    Attributes:
        _benchmark: The benchmark to execute
        _benchmark_input: The input data for the benchmark
        _function: The function to invoke
        _trigger: The trigger to use for invocation
        _out_dir: Directory for storing results
        _deployment_client: The deployment client to use
        _sebs_client: The SeBS client
    """

    def __init__(self, config: ExperimentConfig):
        """Initialize a new PerfCost experiment.

        Args:
            config: Experiment configuration
        """
        super().__init__(config)

    @staticmethod
    def name() -> str:
        """Get the name of the experiment.

        Returns:
            The name "perf-cost"
        """
        return "perf-cost"

    @staticmethod
    def typename() -> str:
        """Get the type name of the experiment.

        Returns:
            The type name "Experiment.PerfCost"
        """
        return "Experiment.PerfCost"

    class RunType(Enum):
        """Types of experiment runs.

        This enum defines the different types of experiment runs:
        - WARM: Measure warm execution performance (reused containers)
        - COLD: Measure cold start performance (new containers)
        - BURST: Measure performance under concurrent burst load
        - SEQUENTIAL: Measure performance with sequential invocations
        """

        WARM = 0
        COLD = 1
        BURST = 2
        SEQUENTIAL = 3

        def str(self) -> str:
            """Get the string representation of the run type.

            Returns:
                The lowercase name of the run type
            """
            return self.name.lower()

    def prepare(self, sebs_client: "SeBS", deployment_client: FaaSSystem) -> None:
        """Prepare the experiment for execution.

        This method sets up the benchmark, function, trigger, and output
        directory for the experiment. It creates or gets the function and
        its HTTP trigger, and prepares the input data for the benchmark.

        Args:
            sebs_client: The SeBS client to use
            deployment_client: The deployment client to use
        """
        # Create benchmark instance
        settings = self.config.experiment_settings(self.name())
        self._benchmark = sebs_client.get_benchmark(
            settings["benchmark"], deployment_client, self.config
        )

        # Prepare benchmark input
        self._benchmark_input = self._benchmark.prepare_input(
            deployment_client.system_resources,
            size=settings["input-size"],
            replace_existing=self.config.update_storage,
        )

        # Get or create function
        self._function = deployment_client.get_function(self._benchmark)

        # Add HTTP trigger if not already present
        triggers = self._function.triggers(Trigger.TriggerType.HTTP)
        if len(triggers) == 0:
            self._trigger = deployment_client.create_trigger(
                self._function, Trigger.TriggerType.HTTP
            )
        else:
            self._trigger = triggers[0]

        # Create output directory
        self._out_dir = os.path.join(sebs_client.output_dir, "perf-cost")
        if not os.path.exists(self._out_dir):
            os.mkdir(self._out_dir)

        # Save clients for later use
        self._deployment_client = deployment_client
        self._sebs_client = sebs_client

    def run(self) -> None:
        """Run the experiment.

        This method runs the experiment with the configured settings.
        If memory sizes are specified, it runs the experiment for each
        memory size, updating the function configuration accordingly.
        Otherwise, it runs the experiment once with the default memory
        configuration.
        """
        settings = self.config.experiment_settings(self.name())

        # Get memory sizes to test
        memory_sizes = settings["memory-sizes"]

        # Run with default memory if no specific sizes are provided
        if len(memory_sizes) == 0:
            self.logging.info("Begin experiment with default memory configuration")
            self.run_configuration(settings, settings["repetitions"])

        # Run for each specified memory size
        for memory in memory_sizes:
            self.logging.info(f"Begin experiment on memory size {memory}")
            # Update function memory configuration
            self._function.config.memory = memory
            self._deployment_client.update_function(
                self._function,
                self._benchmark,
                self._benchmark.container_deployment,
                self._benchmark.container_uri if self._benchmark.container_deployment else "",
            )
            self._sebs_client.cache_client.update_function(self._function)
            # Run experiment with this memory configuration
            self.run_configuration(settings, settings["repetitions"], suffix=str(memory))

    def compute_statistics(self, times: List[float]) -> None:
        """Compute statistical analysis of execution times.

        This method computes basic statistics (mean, median, standard deviation,
        coefficient of variation) and confidence intervals for the given times.
        It computes both parametric (Student's t-distribution) and non-parametric
        confidence intervals.

        Args:
            times: List of execution times in milliseconds
        """
        # Compute basic statistics
        mean, median, std, cv = basic_stats(times)
        self.logging.info(f"Mean {mean} [ms], median {median} [ms], std {std}, CV {cv}")

        # Compute confidence intervals for different confidence levels
        for alpha in [0.95, 0.99]:
            # Parametric confidence interval (Student's t-distribution)
            ci_interval = ci_tstudents(alpha, times)
            interval_width = ci_interval[1] - ci_interval[0]
            ratio = 100 * interval_width / mean / 2.0
            self.logging.info(
                f"Parametric CI (Student's t-distribution) {alpha} from "
                f"{ci_interval[0]} to {ci_interval[1]}, within {ratio}% of mean"
            )

            # Non-parametric confidence interval (Le Boudec's method)
            # Only compute if we have enough samples (> 20)
            if len(times) > 20:
                ci_interval = ci_le_boudec(alpha, times)
                interval_width = ci_interval[1] - ci_interval[0]
                ratio = 100 * interval_width / median / 2.0
                self.logging.info(
                    f"Non-parametric CI {alpha} from {ci_interval[0]} to "
                    f"{ci_interval[1]}, within {ratio}% of median"
                )

    def _run_configuration(
        self,
        run_type: "PerfCost.RunType",
        settings: dict,
        invocations: int,
        repetitions: int,
        suffix: str = "",
    ) -> None:
        """Run a specific experiment configuration.

        This method executes the experiment with the specified run type,
        collecting and recording the results. It handles different run types
        (cold, warm, burst, sequential) appropriately, enforcing cold starts
        when needed and collecting execution statistics.

        Args:
            run_type: Type of run (cold, warm, burst, sequential)
            settings: Experiment settings
            invocations: Number of concurrent invocations
            repetitions: Total number of repetitions to run
            suffix: Optional suffix for output file names (e.g., memory size)
        """

        # Randomize starting value to ensure that it's not the same
        # as in the previous run.
        # Otherwise we could not change anything and containers won't be killed.
        from random import randrange

        self._deployment_client.cold_start_counter = randrange(100)

        """
            Cold experiment: schedule all invocations in parallel.
        """
        file_name = (
            f"{run_type.str()}_results_{suffix}.json"
            if suffix
            else f"{run_type.str()}_results.json"
        )
        self.logging.info(f"Begin {run_type.str()} experiments")
        incorrect_executions = []
        error_executions = []
        error_count = 0
        incorrect_count = 0
        colds_count = 0
        with open(os.path.join(self._out_dir, file_name), "w") as out_f:
            samples_gathered = 0
            client_times = []
            with ThreadPool(invocations) as pool:
                result = ExperimentResult(self.config, self._deployment_client.config)
                result.begin()
                samples_generated = 0

                # Warm up container
                # For "warm" runs, we do it automatically by pruning cold results
                if run_type == PerfCost.RunType.SEQUENTIAL:
                    self._trigger.sync_invoke(self._benchmark_input)

                first_iteration = True
                while samples_gathered < repetitions:

                    if run_type == PerfCost.RunType.COLD or run_type == PerfCost.RunType.BURST:
                        self._deployment_client.enforce_cold_start(
                            [self._function], self._benchmark
                        )

                    time.sleep(5)

                    results = []
                    for i in range(0, invocations):
                        results.append(
                            pool.apply_async(
                                self._trigger.sync_invoke, args=(self._benchmark_input,)
                            )
                        )

                    incorrect = []
                    for res in results:
                        try:
                            ret = res.get()
                            if first_iteration:
                                continue
                            if run_type == PerfCost.RunType.COLD and not ret.stats.cold_start:
                                self.logging.info(f"Invocation {ret.request_id} is not cold!")
                                incorrect.append(ret)
                            elif run_type == PerfCost.RunType.WARM and ret.stats.cold_start:
                                self.logging.info(f"Invocation {ret.request_id} is cold!")
                            else:
                                result.add_invocation(self._function, ret)
                                colds_count += ret.stats.cold_start
                                client_times.append(ret.times.client / 1000.0)
                                samples_gathered += 1
                        except Exception as e:
                            error_count += 1
                            error_executions.append(str(e))
                    samples_generated += invocations
                    if first_iteration:
                        self.logging.info(
                            f"Processed {samples_gathered} warm-up samples, ignoring these results."
                        )
                    else:
                        self.logging.info(
                            f"Processed {samples_gathered} samples out of {repetitions},"
                            f" {error_count} errors"
                        )

                    first_iteration = False

                    if len(incorrect) > 0:
                        incorrect_executions.extend(incorrect)
                        incorrect_count += len(incorrect)

                    time.sleep(5)

                result.end()
                self.compute_statistics(client_times)
                out_f.write(
                    serialize(
                        {
                            **json.loads(serialize(result)),
                            "statistics": {
                                "samples_generated": samples_gathered,
                                "failures": error_executions,
                                "failures_count": error_count,
                                "incorrect": incorrect_executions,
                                "incorrect_count": incorrect_count,
                                "cold_count": colds_count,
                            },
                        }
                    )
                )

    def run_configuration(self, settings: dict, repetitions: int, suffix: str = "") -> None:
        """Run experiments for each configured experiment type.

        This method runs the experiment for each experiment type specified
        in the settings. It dispatches to the appropriate run type handler
        for each experiment type.

        Args:
            settings: Experiment settings
            repetitions: Number of repetitions to run
            suffix: Optional suffix for output file names (e.g., memory size)

        Raises:
            RuntimeError: If an unknown experiment type is specified
        """
        # Run each configured experiment type
        for experiment_type in settings["experiments"]:
            if experiment_type == "cold":
                # Cold start experiments - enforce container recreation
                self._run_configuration(
                    PerfCost.RunType.COLD,
                    settings,
                    settings["concurrent-invocations"],
                    repetitions,
                    suffix,
                )
            elif experiment_type == "warm":
                # Warm execution experiments - reuse containers
                self._run_configuration(
                    PerfCost.RunType.WARM,
                    settings,
                    settings["concurrent-invocations"],
                    repetitions,
                    suffix,
                )
            elif experiment_type == "burst":
                # Burst load experiments - concurrent invocations
                self._run_configuration(
                    PerfCost.RunType.BURST,
                    settings,
                    settings["concurrent-invocations"],
                    repetitions,
                    suffix,
                )
            elif experiment_type == "sequential":
                # Sequential invocation experiments - one at a time
                self._run_configuration(
                    PerfCost.RunType.SEQUENTIAL, settings, 1, repetitions, suffix
                )
            else:
                raise RuntimeError(f"Unknown experiment type {experiment_type} for Perf-Cost!")

    def process(
        self,
        sebs_client: "SeBS",
        deployment_client: FaaSSystem,
        directory: str,
        logging_filename: str,
        extend_time_interval: int,
    ) -> None:
        """Process experiment results and generate a CSV report.

        This method processes the experiment results, downloads additional
        metrics if needed, and generates a CSV report with the results.
        The report includes memory usage, execution times, and other metrics
        for each experiment type and invocation.

        Args:
            sebs_client: The SeBS client to use
            deployment_client: The deployment client to use
            directory: Directory where results are stored
            logging_filename: Filename for logs
            extend_time_interval: Time interval to extend metrics retrieval by (in minutes)
        """

        import glob
        import csv

        with open(os.path.join(directory, "perf-cost", "result.csv"), "w") as csvfile:
            writer = csv.writer(csvfile, delimiter=",")
            writer.writerow(
                [
                    "memory",
                    "type",
                    "is_cold",
                    "exec_time",
                    "connection_time",
                    "client_time",
                    "provider_time",
                    "mem_used",
                ]
            )
            for f in glob.glob(os.path.join(directory, "perf-cost", "*.json")):
                name, extension = os.path.splitext(f)
                if "processed" in f:
                    with open(f) as in_f:
                        config = json.load(in_f)
                        experiments = ExperimentResult.deserialize(
                            config,
                            sebs_client.cache_client,
                            sebs_client.generate_logging_handlers(logging_filename),
                        )
                    fname = os.path.splitext(os.path.basename(f))[0].split("_")
                    if len(fname) > 2:
                        memory = int(fname[2].split("-")[0])
                    else:
                        memory = 0
                    exp_type = fname[0]
                else:

                    if os.path.exists(
                        os.path.join(directory, "perf-cost", f"{name}-processed{extension}")
                    ):
                        self.logging.info(f"Skipping already processed {f}")
                        continue
                    self.logging.info(f"Processing data in {f}")
                    fname = os.path.splitext(os.path.basename(f))[0].split("_")
                    if len(fname) > 2:
                        memory = int(fname[2])
                    else:
                        memory = 0
                    exp_type = fname[0]
                    with open(f, "r") as in_f:
                        config = json.load(in_f)
                        statistics = config["statistics"]
                        experiments = ExperimentResult.deserialize(
                            config,
                            sebs_client.cache_client,
                            sebs_client.generate_logging_handlers(logging_filename),
                        )
                        for func in experiments.functions():
                            if extend_time_interval > 0:
                                times = (
                                    -extend_time_interval * 60 + experiments.times()[0],
                                    extend_time_interval * 60 + experiments.times()[1],
                                )
                            else:
                                times = experiments.times()
                            deployment_client.download_metrics(
                                func,
                                int(times[0]),
                                int(times[1]),
                                experiments.invocations(func),
                                experiments.metrics(func),
                            )
                        # compress! remove output since it can be large but it's useless for us
                        for func in experiments.functions():
                            for id, invoc in experiments.invocations(func).items():
                                # FIXME: compatibility with old results
                                if "output" in invoc.output["result"]:
                                    del invoc.output["result"]["output"]
                                elif "result" in invoc.output["result"]:
                                    del invoc.output["result"]["result"]

                        name, extension = os.path.splitext(f)
                        with open(
                            os.path.join(directory, "perf-cost", f"{name}-processed{extension}"),
                            "w",
                        ) as out_f:
                            out_f.write(
                                serialize(
                                    {**json.loads(serialize(experiments)), "statistics": statistics}
                                )
                            )
                for func in experiments.functions():
                    for request_id, invoc in experiments.invocations(func).items():
                        writer.writerow(
                            [
                                memory,
                                exp_type,
                                invoc.stats.cold_start,
                                invoc.times.benchmark,
                                invoc.times.http_startup,
                                invoc.times.client,
                                invoc.provider_times.execution,
                                invoc.stats.memory_used,
                            ]
                        )
