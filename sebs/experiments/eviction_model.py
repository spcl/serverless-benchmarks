"""Container eviction model experiment implementation.

This module provides the EvictionModel experiment implementation, which
measures how serverless platforms manage function container eviction.
It determines how long idle containers are kept alive before being
recycled by the platform, which affects cold start frequency.

The experiment involves invoking functions at increasing time intervals
and observing when cold starts occur, thus inferring the platform's
container caching and eviction policies.
"""

import logging
import os
import time
from datetime import datetime
from typing import List, Optional, Tuple, TYPE_CHECKING, Dict, Any
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
    """Container eviction model experiment.

    This experiment measures how serverless platforms manage function
    container eviction. It determines how long idle containers are kept
    alive before being recycled by the platform, which affects cold start
    frequency.

    The experiment invokes functions at different time intervals (defined
    in the 'times' list) and observes when cold starts occur, thus inferring
    the platform's container caching and eviction policies.

    Attributes:
        times: List of time intervals (in seconds) between invocations
        _function: Function to invoke
        _trigger: Trigger to use for invocation
        _out_dir: Directory for storing results
        _deployment_client: Deployment client to use
        _sebs_client: SeBS client
    """

    # Time intervals (in seconds) between invocations
    # Uncomment additional intervals as needed for longer tests
    times = [
        1,  # 1 second
        # 2,     # 2 seconds
        # 4,     # 4 seconds
        # 8,     # 8 seconds
        # 15,    # 15 seconds
        # 30,    # 30 seconds
        # 60,    # 1 minute
        # 120,   # 2 minutes
        # 180,   # 3 minutes
        # 240,   # 4 minutes
        # 300,   # 5 minutes
        # 360,   # 6 minutes
        # 480,   # 8 minutes
        # 600,   # 10 minutes
        # 720,   # 12 minutes
        # 900,   # 15 minutes
        # 1080,  # 18 minutes
        # 1200,  # 20 minutes
    ]
    # TODO: temporal fix
    # function_copies_per_time = 5
    function_copies_per_time = 1

    def __init__(self, config: ExperimentConfig):
        """Initialize a new EvictionModel experiment.

        Args:
            config: Experiment configuration
        """
        super().__init__(config)

    @staticmethod
    def name() -> str:
        """Get the name of the experiment.

        Returns:
            The name "eviction-model"
        """
        return "eviction-model"

    @staticmethod
    def typename() -> str:
        """Get the type name of the experiment.

        Returns:
            The type name "Experiment.EvictionModel"
        """
        return "Experiment.EvictionModel"

    @staticmethod
    def accept_replies(port: int, invocations: int) -> None:
        """Accept TCP connections from functions and respond to them.

        This static method acts as a TCP server, accepting connections from
        functions and responding to them. It runs two rounds of connection
        acceptance to ensure functions receive a response. The method logs
        all activity to a file.

        Args:
            port: TCP port to listen on
            invocations: Number of expected function invocations
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
        """Execute a single instance of the eviction model test.

        This method performs two invocations of a function with a sleep interval
        between them. The first invocation should be a cold start, and the second
        will indicate whether the container was evicted during the sleep period.

        Args:
            sleep_time: Time to sleep between invocations (seconds)
            pid: Process ID for logging
            tid: Thread ID for logging
            func: Function to invoke
            payload: Payload to send to the function

        Returns:
            Dictionary with invocation results and timing information

        Raises:
            RuntimeError: If the first invocation fails
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

        time_spent = float(datetime.now().strftime("%s.%f")) - float(end.strftime("%s.%f"))
        seconds_sleep = sleep_time - time_spent
        print(f"PID {pid} TID {tid} with time {sleep_time}, sleep {seconds_sleep}")
        time.sleep(seconds_sleep)

        try:
            second_begin = datetime.now()
            second_res = func.triggers(Trigger.TriggerType.HTTP)[0].sync_invoke(payload)
            second_end = datetime.now()
        except Exception:
            logging.error(f"Second Invocation Failed at function {func.name}")

        return {
            "first": res,
            "first_times": [begin.timestamp(), end.timestamp()],
            "second": second_res,
            "second_times": [second_begin.timestamp(), second_end.timestamp()],
            "invocation": pid,
        }

    @staticmethod
    def process_function(
        repetition: int,
        pid: int,
        invocations: int,
        functions: List[Function],
        times: List[int],
        payload: dict,
    ) -> List[dict]:
        """Process a function with multiple time intervals.

        This method executes multiple functions with different sleep times
        in parallel, starting with the largest sleep time to overlap executions.
        The total time should be equal to the maximum execution time.

        Args:
            repetition: Current repetition number
            pid: Process ID for logging
            invocations: Number of invocations to perform
            functions: List of functions to invoke
            times: List of sleep times corresponding to functions
            payload: Payload to send to functions

        Returns:
            List of dictionaries containing invocation results

        Raises:
            RuntimeError: If any execution fails
        """
        b = multiprocessing.Semaphore(invocations)
        print(f"Begin at PID {pid}, repetition {repetition}")

        threads = len(functions)
        final_results: List[dict] = []
        with ThreadPool(threads) as pool:
            results: List[Optional[AsyncResult]] = [None] * threads
            """
                Invoke multiple functions with different sleep times.
                Start with the largest sleep time to overlap executions; total
                time should be equal to maximum execution time.
            """
            for idx in reversed(range(0, len(functions))):
                payload_copy = payload.copy()
                payload_copy["port"] += idx
                b.acquire()
                results[idx] = pool.apply_async(
                    EvictionModel.execute_instance,
                    args=(times[idx], pid, idx, functions[idx], payload_copy),
                )

            failed = False
            for result in results:
                try:
                    assert result
                    res = result.get()
                    res["repetition"] = repetition
                    final_results.append(res)
                except Exception as e:
                    print(e)
                    failed = True
            if failed:
                print("Execution failed!")
                raise RuntimeError()
        return final_results

    def prepare(self, sebs_client: "SeBS", deployment_client: FaaSSystem) -> None:
        """Prepare the experiment for execution.

        This method sets up the benchmark, functions, and output directory for
        the experiment. It creates a separate function for each time interval
        and copy combination, allowing for parallel testing of different
        eviction times.

        Args:
            sebs_client: The SeBS client to use
            deployment_client: The deployment client to use
        """
        # Get the server-reply benchmark
        self._benchmark = sebs_client.get_benchmark(
            "040.server-reply", deployment_client, self.config
        )
        self._deployment_client = deployment_client
        self._result = ExperimentResult(self.config, deployment_client.config)

        # Create function names for each time interval and copy
        name = deployment_client.default_function_name(self._benchmark)
        self.functions_names = [
            f"{name}-{time}-{copy}"
            for time in self.times
            for copy in range(self.function_copies_per_time)
        ]

        # Create output directory
        self._out_dir = os.path.join(sebs_client.output_dir, "eviction-model")
        if not os.path.exists(self._out_dir):
            os.mkdir(self._out_dir)

        self.functions = []

        for fname in self.functions_names:
            # if self._benchmark.functions and fname in self._benchmark.functions:
            # self.logging.info(f"Skip {fname}, exists already.")
            #    continue
            self.functions.append(deployment_client.get_function(self._benchmark, func_name=fname))

    def run(self) -> None:
        """Execute the eviction model experiment.

        This method runs the main eviction model experiment by:
        1. Setting up server instances to handle function responses
        2. Executing parallel invocations with different sleep times
        3. Collecting and storing results

        The experiment determines container eviction patterns by measuring
        whether functions experience cold starts after different idle periods.
        """

        settings = self.config.experiment_settings(self.name())
        invocations = settings["invocations"]
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
        results: Dict[int, List[List[Dict[str, Any]]]] = {}

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
                local_results: List[AsyncResult] = []
                servers_results: List[AsyncResult] = []

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
                    result.get()

                for result in local_results:
                    local_ret = result.get()
                    for i, val in enumerate(local_ret):
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
