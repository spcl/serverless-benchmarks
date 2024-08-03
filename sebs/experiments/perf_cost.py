import json
import os
import time
import glob
from datetime import datetime
from enum import Enum
from multiprocessing.pool import ThreadPool
from typing import List, TYPE_CHECKING

from sebs.faas.system import System as FaaSSystem
from sebs.faas.function import Trigger, Benchmark, Function, Workflow, ExecutionResult
from sebs.azure.azure import Azure
from sebs.aws.aws import AWS
from sebs.gcp.gcp import GCP
from sebs.experiments.experiment import Experiment
from sebs.experiments.result import Result as ExperimentResult
from sebs.experiments.config import Config as ExperimentConfig
from sebs.utils import serialize, download_measurements, connect_to_redis_cache
from sebs.statistics import basic_stats, ci_tstudents, ci_le_boudec

import pandas as pd
import numpy as np

# import cycle
if TYPE_CHECKING:
    from sebs import SeBS


class PerfCost(Experiment):
    def __init__(self, config: ExperimentConfig, is_workflow: bool):
        super().__init__(config)
        self.is_workflow = is_workflow

    @staticmethod
    def name() -> str:
        return "perf-cost"

    @staticmethod
    def typename() -> str:
        return "Experiment.PerfCost"

    class RunType(Enum):
        WARM = 0
        COLD = 1
        BURST = 2
        SEQUENTIAL = 3

        def str(self) -> str:
            return self.name.lower()

    def prepare(self, sebs_client: "SeBS", deployment_client: FaaSSystem):
        self.num_expected_payloads = -1

        # create benchmark instance
        settings = self.config.experiment_settings(self.name())
        self._benchmark = sebs_client.get_benchmark(
            settings["benchmark"], deployment_client, self.config
        )

        # prepare benchmark input
        self._benchmark_input = self._benchmark.prepare_input(
            deployment_client.system_resources,
            size=settings["input-size"],
            replace_existing=self.config.update_storage,
        )
        if self.is_workflow:
            self._function = deployment_client.get_workflow(self._benchmark)
        else:
            self._function = deployment_client.get_function(self._benchmark)

        # add HTTP trigger
        if self.is_workflow and not isinstance(deployment_client, Azure):
            trigger_type = Trigger.TriggerType.LIBRARY
        else:
            trigger_type = Trigger.TriggerType.HTTP
        triggers = self._function.triggers(trigger_type)
        if len(triggers) == 0:
            self._trigger = deployment_client.create_trigger(self._function, trigger_type)
        else:
            self._trigger = triggers[0]

        self._out_dir = os.path.join(sebs_client.output_dir, "perf-cost")
        if not os.path.exists(self._out_dir):
            os.mkdir(self._out_dir)
        self._deployment_client = deployment_client
        self._sebs_client = sebs_client

    def run(self):
        settings = self.config.experiment_settings(self.name())

        # Execution on systems where memory configuration is not provided
        memory_sizes = settings["memory-sizes"]
        if len(memory_sizes) == 0:
            self.logging.info("Begin experiment")
            self.run_configuration(settings, settings["repetitions"])
        for memory in memory_sizes:
            self.logging.info(f"Begin experiment on memory size {memory}")
            self._function.config.memory = memory

            #code_package = self._sebs_client.get_benchmark(
            #    settings["benchmark"], self._deployment_client, self.config
            #)
            platform = self._deployment_client.name()
            if self.is_workflow and platform != "azure":
                for func in self._function.functions:
                    func.memory = memory
                    self._deployment_client.update_function(func, self._benchmark)
            self._sebs_client.cache_client.update_benchmark(self._function)

            self.run_configuration(settings, settings["repetitions"], suffix=str(memory))

    def compute_statistics(self, times: List[float]):

        mean, median, std, cv = basic_stats(times)
        self.logging.info(f"Mean {mean} [ms], median {median} [ms], std {std}, CV {cv}")
        for alpha in [0.95, 0.99]:
            ci_interval = ci_tstudents(alpha, times)
            interval_width = ci_interval[1] - ci_interval[0]
            ratio = 100 * interval_width / mean / 2.0
            self.logging.info(
                f"Parametric CI (Student's t-distribution) {alpha} from "
                f"{ci_interval[0]} to {ci_interval[1]}, within {ratio}% of mean"
            )

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
    ):

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

        platform = self._deployment_client.name()
        result_dir = os.path.join(self._out_dir, settings["benchmark"], platform)
        os.makedirs(result_dir, exist_ok=True)

        def _download_measurements(request_id):
            try:
                redis = connect_to_redis_cache(
                    self._deployment_client.config.resources.redis_host,
                    self._deployment_client.config.resources.redis_password,
                )
                print("trying to download for function.name = ", self._function.name)
                payloads = download_measurements(
                    redis, self._function.name, result.begin_time, request_id
                )
                return payloads
            except:
                return None

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
                measurements = []
                while samples_gathered < repetitions:
                    funcs = [self._function]
                    if isinstance(self._function, Workflow) and platform != "azure":
                        funcs = self._function.functions
                    if run_type == PerfCost.RunType.COLD or run_type == PerfCost.RunType.BURST:
                        self._deployment_client.enforce_cold_start(funcs, self._benchmark)

                    time.sleep(10)

                    results = []
                    if first_iteration == True:
                        for i in range(0, 1):
                            results.append(
                                pool.apply_async(
                                    self._trigger.sync_invoke, args=(self._benchmark_input,)
                                )
                            )
                    else:
                        for i in range(0, invocations):
                            results.append(
                                pool.apply_async(
                                    self._trigger.sync_invoke, args=(self._benchmark_input,)
                                )
                            )

                    incorrect = []
                    first_iteration_request_ids = []
                    for res in results:
                        try:
                            ret = res.get()

                            if ret.stats.failure:
                                raise RuntimeError("Failed invocation")

                            if first_iteration:
                                first_iteration_request_ids.append(ret.request_id)
                                continue

                            was_cold_start = ret.stats.cold_start
                            if self.is_workflow:
                                self.logging.info(f"Downloading measurements for {ret.request_id}")
                                payloads = _download_measurements(ret.request_id)
                                retries = 0
                                while not payloads and retries < 10:
                                    self.logging.info("Failed to download measurments. Retrying...")
                                    payloads = _download_measurements(ret.request_id)
                                    retries += 1
                                if retries > 0:
                                    self.logging.info("Downloaded all measurments.")

                                df = pd.DataFrame(payloads)
                                if df.shape[0] > 0:
                                    # ensure that first invocation was warm.
                                    df = df.sort_values(["start"]).reset_index(drop=True)
                                    was_cold_start = df.at[0, "is_cold"]
                                else:
                                    raise RuntimeError(
                                        f"Did not find measurements for {ret.request_id}"
                                    )

                            invalid = (
                                run_type == PerfCost.RunType.COLD and not was_cold_start
                            ) or (run_type == PerfCost.RunType.WARM and was_cold_start)
                            if self.is_workflow:
                                invalid = invalid or (self.num_expected_payloads != len(payloads))

                            if invalid:
                                msg = (
                                    f"Invalid invocation {ret.request_id} "
                                    f"cold: {was_cold_start} "
                                )

                                if self.is_workflow:
                                    msg += f"measurements: {len(payloads)}/{self.num_expected_payloads} "

                                msg += f"on experiment {run_type.str()}!"

                                self.logging.info(msg)
                                incorrect.append(ret)

                            else:
                                result.add_invocation(self._function, ret)
                                colds_count += ret.stats.cold_start
                                client_times.append(ret.times.client / 1000.0)
                                samples_gathered += 1
                                if self.is_workflow:
                                    measurements += payloads
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

                    if self.is_workflow and self.num_expected_payloads == -1:
                        self.logging.info(f"Downloading measurements for first iterations")
                        payloads = _download_measurements(None)
                        retries = 0
                        while not payloads and retries < 10:
                            self.logging.info("Failed to download measurments. Retrying...")
                            payloads = _download_measurements(None)
                            retries += 1
                        if retries > 0:
                            self.logging.info("Downloaded all measurments.")

                        df = pd.DataFrame(payloads)

                        df = df[df["request_id"].isin(first_iteration_request_ids)]
                        if df.shape[0] == 0:
                            raise RuntimeError(
                                "Did not download any measurements. The workflow is likely to fail everytime."
                            )

                        self.num_expected_payloads = int(df.groupby("request_id").size().mean())

                        self.logging.info(
                            f"Will be expecting {self.num_expected_payloads} measurements"
                        )
                        file_name = f"{run_type.str()}_{suffix}_first_iteration.csv"
                        csv_path = os.path.join(result_dir, file_name)
                        write_header = not os.path.exists(csv_path)
                        df.to_csv(csv_path, index=False, mode="a", header=write_header)

                    if len(incorrect) > 0:
                        incorrect_executions.extend(incorrect)
                        incorrect_count += len(incorrect)

                    time.sleep(5)

                result.end()
                self.compute_statistics(client_times)

                file_name = f"{run_type.str()}_{suffix}.csv"
                csv_path = os.path.join(result_dir, file_name)

                write_header = not os.path.exists(csv_path)
                df = pd.DataFrame(measurements)
                df.to_csv(csv_path, index=False, mode="a", header=write_header)

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

    def run_configuration(self, settings: dict, repetitions: int, suffix: str = ""):

        for experiment_type in settings["experiments"]:
            if experiment_type == "cold":
                self._run_configuration(
                    PerfCost.RunType.COLD,
                    settings,
                    settings["concurrent-invocations"],
                    repetitions,
                    suffix,
                )
            elif experiment_type == "warm":
                self._run_configuration(
                    PerfCost.RunType.WARM,
                    settings,
                    settings["concurrent-invocations"],
                    repetitions,
                    suffix,
                )
            elif experiment_type == "burst":
                self._run_configuration(
                    PerfCost.RunType.BURST,
                    settings,
                    settings["concurrent-invocations"],
                    repetitions,
                    suffix,
                )
            elif experiment_type == "sequential":
                self._run_configuration(
                    PerfCost.RunType.SEQUENTIAL, settings, 1, repetitions, suffix
                )
            else:
                raise RuntimeError(f"Unknown experiment type {experiment_type} for Perf-Cost!")

    def process_workflow(
        self,
        sebs_client: "SeBS",
        deployment_client: FaaSSystem,
        directory: str,
        logging_filename: str,
        extend_time_interval: int,
    ):

        benchmark_name = self.config._experiment_configs[PerfCost.name()]["benchmark"]
        platform = deployment_client.name()
        # result_dir = os.path.join(directory, "perf-cost", benchmark_name, platform+"_vpc_*")
        result_dir = os.path.join(directory, "perf-cost", benchmark_name, platform)

        settings = self.config.experiment_settings(self.name())
        code_package = sebs_client.get_benchmark(
            settings["benchmark"], deployment_client, self.config
        )

        if isinstance(deployment_client, Azure):
            workflow_name = deployment_client.default_function_name(code_package)
        else:
            workflow_name = benchmark_name  # deployment_client.default_benchmark_name(code_package)

        for f in glob.glob(os.path.join(result_dir, "*.csv")):
            filename = os.path.splitext(os.path.basename(f))[0]

            print("Filename: ", filename)

            processed_path = os.path.join(result_dir, filename + "_processed.csv")
            processed = "processed" in f or os.path.exists(processed_path)
            if processed:
                continue

            df = pd.read_csv(f)

            requests = dict()
            for i in range(df.shape[0]):
                id = df.at[i, "provider.request_id"]
                start = datetime.fromtimestamp(df.at[i, "start"])
                end = datetime.fromtimestamp(df.at[i, "end"])
                res = ExecutionResult.from_times(start, end)
                res.request_id = id

                requests[id] = res

            times = (df["start"].min(), df["end"].max())
            if extend_time_interval > 0:
                times = (
                    -extend_time_interval * 60 + times[0],
                    extend_time_interval * 60 + times[1],
                )

            metrics = dict()

            if isinstance(deployment_client, Azure):
                func_names = [workflow_name]
            else:
                workflow_name = workflow_name.replace(".", "_")
                workflow_name = workflow_name.replace("-", "_")
                runtime_version = self.config.runtime.version
                runtime_version = runtime_version.replace(".", "_")
                if isinstance(deployment_client, GCP):
                    prefix = "function-" + workflow_name + "_python_" + runtime_version + "___"
                else:
                    prefix = workflow_name + "_python_" + runtime_version + "___"
                func_names = [prefix + fn for fn in df.func.unique()]
                print("looking for", func_names)

            for func_name in func_names:
                deployment_client.download_metrics(
                    func_name,
                    *times,
                    requests,
                    metrics,
                )

            df["provider.execution_duration"] = np.nan
            df["provider.init_duration"] = np.nan
            df["max_mem_used"] = np.nan
            df["billing.duration"] = np.nan
            df["billing.mem"] = np.nan
            df["billing.gbs"] = np.nan
            for i in range(df.shape[0]):
                id = df.at[i, "provider.request_id"]
                df.at[i, "provider.execution_duration"] = requests[id].provider_times.execution
                df.at[i, "provider.init_duration"] = requests[id].provider_times.initialization
                df.at[i, "max_mem_used"] = requests[id].stats.memory_used
                df.at[i, "billing.duration"] = requests[id].billing.billed_time
                df.at[i, "billing.mem"] = requests[id].billing.memory
                df.at[i, "billing.gbs"] = requests[id].billing.gb_seconds

            df.to_csv(processed_path, index=False)

    def process(
        self,
        sebs_client: "SeBS",
        deployment_client: FaaSSystem,
        directory: str,
        logging_filename: str,
        extend_time_interval: int,
    ):

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
                                *times,
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
