import logging
import os
import time
from datetime import datetime
from typing import List, Optional, Tuple, TYPE_CHECKING
import multiprocessing
from multiprocessing.pool import AsyncResult, ThreadPool

from sebs.faas.system import System as FaaSSystem
from sebs.faas.function import Function, Trigger
from sebs.experiments import Experiment, ExperimentResult
from sebs.experiments.config import Config as ExperimentConfig
from sebs.utils import serialize

if TYPE_CHECKING:
    from sebs import SeBS


class EvictionModel(Experiment):
    """
    Experiment to model the eviction behavior of FaaS platforms.

    This experiment invokes multiple copies of a function with varying sleep times
    between two invocations to determine if the function instance is evicted
    from the underlying infrastructure.

    Configuration in `experiments.json` under "eviction-model":
        - "invocations": Number of parallel invocation series.
        - "sleep": (Not directly used in current logic, but might be intended for future use).
        - "repetitions": Number of times to repeat the entire experiment sequence.
        - "function_copy_idx": Index to select a subset of function copies for this run.
        - "client-port": Starting port number for server replies.
    """
    times = [
        1,
        # 2,
        # 4,
        # 8,
        # 15,
        # 30,
        # 60,
        # 120,
        # 180,
        # 240,
        # 300,
        # 360,
        # 480,
        # 600,
        # 720,
        # 900,
        # 1080,
        # 1200,
    ]
    # TODO: temporal fix
    # function_copies_per_time = 5
    function_copies_per_time = 1

    def __init__(self, config: ExperimentConfig):
        """
        Initialize the EvictionModel experiment.

        :param config: Experiment configuration.
        """
        super().__init__(config)

    @staticmethod
    def name() -> str:
        """Return the name of the experiment."""
        return "eviction-model"

    @staticmethod
    def typename() -> str:
        """Return the type name of this experiment class."""
        return "Experiment.EvictionModel"

    @staticmethod
    def accept_replies(port: int, invocations: int):
        """
        A simple server to accept replies from invoked functions.

        Listens on a specified port for a given number of connections, twice.
        This is used by the '040.server-reply' benchmark to confirm function execution.
        Writes logs to `server_{invocations}.log`.

        :param port: The port number to listen on.
        :param invocations: The number of connections to accept in each of the two phases.
        """
        with open(f"server_{invocations}.log", "w") as f:
            import socket

            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            s.bind(("", port))
            s.listen(invocations + 1)

            print(f"Listen on {port} and wait for {invocations}", file=f)
            # First repetition
            connections: List[Tuple[socket.socket, str]] = []
            # wait for functions to connect
            while len(connections) < invocations:
                c, addr = s.accept()
                print(f"Accept connection from {addr}", file=f)
                connections.append((c, addr))

            for connection, addr in connections:
                print(f"Send message to {addr}", file=f)
                connection.send(b"accepted")
                connection.close()

            # Second repetition
            connections = []
            # wait for functions to connect
            while len(connections) < invocations:
                c, addr = s.accept()
                print(f"Accept connection from {addr}", file=f)
                connections.append((c, addr))

            for connection, addr in connections:
                print(f"Send message to {addr}", file=f)
                connection.send(b"accepted")
                connection.close()

            s.close()

    @staticmethod
    def execute_instance(
        sleep_time: int, pid: int, tid: int, func: Function, payload: dict
    ) -> dict:
        """
        Executes a single function instance twice with a specified sleep time in between.

        This function is intended to be run in a separate thread. It performs two
        synchronous HTTP invocations of the given function. The first invocation
        is checked for cold start status.

        :param sleep_time: The target time in seconds to wait between the end of the
                           first invocation and the start of the second.
        :param pid: Process ID (or an equivalent identifier for the parallel invocation series).
        :param tid: Thread ID (or an equivalent identifier for the specific function copy/time).
        :param func: The Function object to invoke.
        :param payload: The payload for the function invocation.
        :return: A dictionary containing the results of both invocations and their timestamps.
        :raises RuntimeError: If the first invocation fails.
        """
        try:
            print(f"Process {pid} Thread {tid} Invoke function {func.name} with {payload} now!")
            begin = datetime.now()
            res = func.triggers(Trigger.TriggerType.HTTP)[0].sync_invoke(payload)
            end = datetime.now()
            if not res.stats.cold_start:
                logging.error(
                    f"First invocation not cold on func {func.name} time {sleep_time} "
                    f"pid {pid} tid {tid} id {res.request_id}"
                )
        except Exception as e:
            logging.error(f"First Invocation Failed at function {func.name}, {e}")
            raise RuntimeError()

        # Calculate actual sleep time needed to match the target `sleep_time`
        # This accounts for the time taken by the first invocation and other overheads.
        # The original code had `time` instead of `sleep_time` in the print statement,
        # which might be a typo. Assuming `sleep_time` is the intended variable.
        time_spent_after_invocation = (datetime.now() - end).total_seconds()
        seconds_to_sleep_precisely = sleep_time - time_spent_after_invocation
        # Ensure sleep is not negative if invocation took longer than sleep_time
        actual_sleep_duration = max(0, seconds_to_sleep_precisely)

        print(f"PID {pid} TID {tid} with target sleep {sleep_time}, actual sleep {actual_sleep_duration:.2f}s")
        time.sleep(actual_sleep_duration)

        second_res = None
        try:
            second_begin = datetime.now()
            second_res = func.triggers(Trigger.TriggerType.HTTP)[0].sync_invoke(payload)
            second_end = datetime.now()
        except Exception as e:
            logging.error(f"Second Invocation Failed at function {func.name}, error: {e}")
            # Store failure or partial result if needed, here we just log
            # and second_res will remain None or its last assigned value.
            # Depending on requirements, one might want to raise an error or return specific failure indicators.
            # For now, we'll let it return the partial result.
            second_begin = datetime.now() # Placeholder if it failed before starting
            second_end = datetime.now() # Placeholder

        return {
            "first": res,
            "first_times": [begin.timestamp(), end.timestamp()],
            "second": second_res, # This could be None if the second invocation failed
            "second_times": [second_begin.timestamp(), second_end.timestamp()],
            "invocation": pid, # Identifier for the parallel invocation series
        }

    @staticmethod
    def process_function(
        repetition: int,
        pid: int,
        invocations_semaphore_val: int, # Renamed from 'invocations' to avoid confusion
        functions: List[Function],
        times: List[int],
        payload: dict,
    ) -> List[dict]:
        """
        Process a set of functions in parallel threads for a single repetition and process ID.

        Each function in the `functions` list is invoked according to `execute_instance`
        with a corresponding sleep time from the `times` list. A semaphore is used to
        limit the number of concurrent threads to `invocations_semaphore_val`.

        :param repetition: The current repetition number of the experiment.
        :param pid: Process ID (or identifier for this parallel set of function tests).
        :param invocations_semaphore_val: Value for the semaphore to limit concurrency.
        :param functions: List of Function objects to test.
        :param times: List of sleep times corresponding to each function.
        :param payload: Base payload for function invocations (port will be adjusted per thread).
        :return: A list of dictionaries, where each dictionary is the result from `execute_instance`.
        :raises RuntimeError: If any of the threaded `execute_instance` calls fail.
        """
        # Semaphore to limit concurrency based on the 'invocations' config,
        # which seems to mean number of parallel series rather than total invocations here.
        semaphore = multiprocessing.Semaphore(invocations_semaphore_val)
        print(f"Begin at PID {pid}, repetition {repetition}")

        num_threads = len(functions)
        final_results: List[dict] = []
        with ThreadPool(num_threads) as pool:
            async_results: List[Optional[AsyncResult]] = [None] * num_threads
            """
                Invoke multiple functions with different sleep times.
                Start with the largest sleep time to overlap executions; total
                time should be equal to maximum execution time.
            """
            for idx in reversed(range(num_threads)):
                payload_copy = payload.copy()
                payload_copy["port"] += idx # Assign a unique port for each function instance
                semaphore.acquire()
                try:
                    async_results[idx] = pool.apply_async(
                        EvictionModel.execute_instance,
                        args=(times[idx], pid, idx, functions[idx], payload_copy),
                    )
                except Exception as e:
                    semaphore.release() # Ensure semaphore is released on submission error
                    logging.error(f"Error submitting task for function {functions[idx].name}: {e}")
                    # Decide how to handle: raise, or mark as failed and continue?
                    # For now, let's re-raise to indicate a problem with setup/submission.
                    raise

            failed_tasks = False
            for idx, result_handle in enumerate(async_results):
                try:
                    if result_handle:
                        res = result_handle.get()
                        res["repetition"] = repetition
                        final_results.append(res)
                    else:
                        # This case should ideally not happen if apply_async succeeded.
                        logging.error(f"No result handle for function index {idx}, PID {pid}")
                        failed_tasks = True
                except Exception as e:
                    logging.error(f"Task for function index {idx} (PID {pid}) failed: {e}")
                    failed_tasks = True
                finally:
                    semaphore.release() # Release semaphore once task is processed (get() returns or raises)

            if failed_tasks:
                print(f"Execution failed for one or more tasks in PID {pid}, repetition {repetition}!")
                # Depending on desired behavior, could raise RuntimeError here or allow partial results.
                # For now, we'll allow partial results and print a message.
                # raise RuntimeError("One or more threaded tasks failed.")
        return final_results

    def prepare(self, sebs_client: "SeBS", deployment_client: FaaSSystem):
        """
        Prepare the experiment environment.

        Retrieves the '040.server-reply' benchmark, sets up result storage,
        and creates or retrieves function instances based on configured times and copies.

        :param sebs_client: The SeBS client instance.
        :param deployment_client: The FaaS system client (e.g., AWS, Azure).
        """
        self._benchmark = sebs_client.get_benchmark(
            "040.server-reply", deployment_client, self.config
        )
        self._deployment_client = deployment_client
        self._result = ExperimentResult(self.config, deployment_client.config)
        name = deployment_client.default_function_name(self._benchmark)
        self.functions_names = [
            f"{name}-{time}-{copy}"
            for time in self.times
            for copy in range(self.function_copies_per_time)
        ]
        self._out_dir = os.path.join(sebs_client.output_dir, "eviction-model")
        if not os.path.exists(self._out_dir):
            os.mkdir(self._out_dir)
        self.functions = []

        for fname in self.functions_names:
            # if self._benchmark.functions and fname in self._benchmark.functions:
            # self.logging.info(f"Skip {fname}, exists already.")
            #    continue
            self.functions.append(deployment_client.get_function(self._benchmark, func_name=fname))

    def run(self):
        """
        Run the EvictionModel experiment.

        Orchestrates the parallel invocation of functions with varying sleep times
        across multiple repetitions and processes, collecting and saving the results.
        Uses multiprocessing.Pool for parallelism.
        """
        settings = self.config.experiment_settings(self.name())
        invocations = settings["invocations"] # Number of parallel series of tests
        sleep = settings["sleep"]
        repetitions = settings["repetitions"]
        invocation_idx = settings["function_copy_idx"]
        port = settings["client-port"]
        from requests import get

        ip = get("http://checkip.amazonaws.com/").text.rstrip()

        # function_names = self.functions_names[invocation_idx :: self.function_copies_per_time]
        # flake8 issue
        # https://github.com/PyCQA/pycodestyle/issues/373
        functions = self.functions[invocation_idx :: self.function_copies_per_time]  # noqa
        results = {}

        # Disable logging - otherwise we have RLock that can't get be pickled
        for func in functions:
            # func.disable_logging()
            for tr in func.triggers_all():
                del tr._logging_handlers
        # self.disable_logging()
        # del self.logging

        for t in self.times:
            results[t] = []

        fname = f"results_{invocations}_{repetitions}_{sleep}.json"

        """
            Allocate one process for each invocation => process N invocations in parallel.
            Each process uses M threads to execute in parallel invocations,
            with a different time sleep between executions.

            The result: repeated N invocations for M different imes.
        """
        threads = len(self.times)
        with multiprocessing.Pool(processes=(invocations + threads)) as pool:
            for i in range(0, repetitions):
                """
                Attempt to kill all existing containers.
                """
                # for func in functions:
                #    self._deployment_client.enforce_cold_start(func)
                # time.sleep(5)
                for _, t in enumerate(self.times):
                    results[t].append([])
                local_results = []
                servers_results = []

                """
                    Start M server instances. Each one handles one set of invocations.
                """
                for j in range(0, threads):
                    servers_results.append(
                        pool.apply_async(EvictionModel.accept_replies, args=(port + j, invocations))
                    )

                """
                    Start N parallel invocations
                """
                for j in range(0, invocations):
                    payload = {"ip-address": ip, "port": port}
                    print(payload)
                    local_results.append(
                        pool.apply_async(
                            EvictionModel.process_function,
                            args=(i, j, invocations, functions, self.times, payload),
                        )
                    )

                time.sleep(10)
                import sys

                sys.stdout.flush()
                """
                    Rethrow exceptions if appear
                """
                for result in servers_results:
                    ret = result.get()

                for result in local_results:
                    ret = result.get()
                    for i, val in enumerate(ret):
                        results[self.times[i]][-1].append(val)

                """
                    Make sure that parallel invocations are truly parallel,
                    i.e. no execution happens after another one finished.
                """
                # verify_results(results)

            with open(os.path.join(self._out_dir, fname), "w") as out_f:
                # print(results)
                print(f"Write results to {os.path.join(self._out_dir, fname)}")
                out_f.write(serialize(results))
        # func = self._deployment_client.get_function(
        #    self._benchmark, self.functions_names[0]
        # )
        # self._deployment_client.enforce_cold_start(func)
        # ret = func.triggers[0].async_invoke(payload)
        # result = ret.result()
        # print(result.stats.cold_start)
        # self._result.add_invocation(func, result)
        # print(serialize(self._result))
