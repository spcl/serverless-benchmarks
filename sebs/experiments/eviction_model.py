import json
import logging
import os
from datetime import datetime
from time import sleep
from typing import List
import multiprocessing
from multiprocessing import pool
from multiprocessing.pool import ThreadPool

from sebs.faas.system import System as FaaSSystem
from sebs.faas.function import Function
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

    def execute_instance(time: int, pid: int, tid: int, func: Function, payload: dict):


        #return f"{time}_{pid}_{tid}"
        try:
            print(f"{pid} {tid} Invoke function {func.name} now!")
            begin = datetime.now()
            res = func.triggers[0].sync_invoke(payload)
            end = datetime.now()
            if not res.stats.cold_start:
                logging.error(f"First invocation not cold on func {func.name} time {time} pid {pid} tid {tid} id {res.request_id}")
        except Exception as e:
            logging.error(f"First Invocation Failed at function {func.name}, {e}")
            raise RuntimeError()

        time_spent = float(datetime.now().strftime('%s.%f')) - float(end.strftime('%s.%f'))
        seconds_sleep = time - time_spent
        print(f"PID {pid} TID {tid} with time {time}, sleep {seconds_sleep}")

        try:
            second_begin = datetime.now()
            second_res = func.triggers[0].sync_invoke(payload)
            second_end = datetime.now()
        except:
            logging.error(f"Second Invocation Failed at function {func.name}")

        return {
            "first": res,
            "first_times": [begin.timestamp(), end.timestamp()],
            "second": second_res,
            "second_times": [second_begin.timestamp(), second_end.timestamp()],
            "invocation": pid
        }

    def process_function(repetition: int, pid: int, invocations: int, functions: List[Function], times: List[int], payload: dict):

        b = multiprocessing.Semaphore(invocations)
        b.acquire()
        logging.info(f"Begin at PID {pid}, repetition {repetition}")
        results = []

        threads = len(functions)
        final_results = []
        with ThreadPool(threads) as pool:
            results = [None] * threads
            for idx in reversed(range(0, len(functions))):
                results[idx] = pool.apply_async(EvictionModel.execute_instance,
                        args=(times[idx], pid, idx, functions[idx], payload)
                )
            failed = False
            for result in results:
                try:
                    res = result.get()
                    res["repetition"] = repetition
                    final_results.append(res)
                except Exception as e:
                    logging.error(e)
                    failed = True
            if failed:
                raise RuntimeError()
        return final_results

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
        self._out_dir = os.path.join(sebs_client.output_dir, "eviction-model")
        if not os.path.exists(self._out_dir):
            os.mkdir(self._out_dir)
        self.functions = []

        for fname in self.functions_names:
            #if self._benchmark.functions and fname in self._benchmark.functions:
                # self.logging.info(f"Skip {fname}, exists already.")
            #    continue
            self.functions.append(deployment_client.get_function(self._benchmark, func_name=fname))

    def run(self):

        settings = self.config.experiment_settings(self.name())
        invocations = settings["invocations"]
        sleep = settings["sleep"]
        repetitions = settings["repetitions"]
        invocation_idx = settings["function_copy_idx"]
        function_names = self.functions_names[invocation_idx::self.function_copies_per_time]
        functions = self.functions[invocation_idx::self.function_copies_per_time]
        results = {}
        payload = {"sleep": 1}

        for func in functions:
            func.disable_logging()
        self.disable_logging()

        for t in self.times:
            results[t] = []

        fname = f"results_{invocations}_{repetitions}_{sleep}.json"
        with multiprocessing.Pool(processes=invocations) as pool:
            for i in range(0, repetitions):
                for _, t in enumerate(self.times):
                    results[t].append([])
                local_results = []
                #self._deployment_client.enforce_cold_starts(functions)
                for j in range(0, invocations):
                    local_results.append(
                        pool.apply_async(EvictionModel.process_function,
                            args=(
                                i, j, invocations, functions, self.times, payload
                            )
                        )
                    )
                for result in local_results:
                    ret = result.get()
                    for i, val in enumerate(ret):
                        results[self.times[i]][-1].append(val)

            with open(os.path.join(self._out_dir, fname), "w") as out_f:
                out_f.write(serialize(results))
        #func = self._deployment_client.get_function(
        #    self._benchmark, self.functions_names[0]
        #)
        #self._deployment_client.enforce_cold_start(func)
        #ret = func.triggers[0].async_invoke(payload)
        #result = ret.result()
        #print(result.stats.cold_start)
        #self._result.add_invocation(func, result)
        #print(serialize(self._result))
