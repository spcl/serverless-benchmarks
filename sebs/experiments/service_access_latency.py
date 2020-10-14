import csv
import json
import os
import random
import shutil
import socket
import uuid
from datetime import datetime
from itertools import repeat
from multiprocessing.dummy import Pool as ThreadPool

from sebs.benchmark import Benchmark
from sebs.faas.system import System as FaaSSystem
from sebs.experiments.experiment import Experiment
from sebs.experiments.config import Config as ExperimentConfig


class ServiceAccessLatency(Experiment):
    def __init__(self, config: ExperimentConfig):
        super().__init__(config)

    def prepare(self, sebs_client: "SeBS", deployment_client: FaaSSystem):

        # deploy network test function
        from sebs import SeBS
        from sebs.faas.function import Trigger

        self._benchmark = sebs_client.get_benchmark(
            "040.server-reply", deployment_client, self.config
        )
        self._function = deployment_client.get_function(self._benchmark)

        triggers = self._function.triggers(Trigger.TriggerType.HTTP)
        if len(triggers) == 0:
          self._trigger = deployment_client.create_trigger(self._function, Trigger.TriggerType.HTTP)
        else:
          self._trigger = triggers[0]

        self._storage = deployment_client.get_storage(replace_existing=True)
        self.benchmark_input = self._benchmark.prepare_input(
            storage=self._storage, size="test"
        )
        self._out_dir = os.path.join(sebs_client.output_dir, self.name())
        if not os.path.exists(self._out_dir):
            os.mkdir(self._out_dir)

        self._deployment_client = deployment_client
        from requests import get
        self.ip = get("http://checkip.amazonaws.com/").text.rstrip()

    def cold_invocation(self):
        settings = self.config.experiment_settings(self.name())
        port = settings['local-port']
        repetitions = settings["repetitions"]
        input_benchmark = {
            "caller-address": self.ip,
            "caller-port": port,
            "holepunching-address": settings["holepunching-address"],
            "holepunching-port": settings["holepunching-port"],
            "keep-alive-time": 0,
            "function-id": str(uuid.uuid4())[0:8],
            **self.benchmark_input,
        }

        output_file = os.path.join(self._out_dir, "cold_invocation.csv")
        with open(output_file, "w") as csvfile:
            writer = csv.writer(csvfile, delimiter=",")
            writer.writerow(
                [
                    "repetition",
                    "is_cold",
                    "start_timestamp",
                    "receive_timestamp",
                    "request_id",
                ]
            )
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind(('', port))

            for i in range(repetitions):
                print(f"Starting with repetition {i}")
                self._deployment_client.enforce_cold_start(
                    self._function, self._benchmark
                )

                begin = datetime.now()
                fut = self._trigger.async_invoke(input_benchmark)
                msg, addr = server_socket.recvfrom(1024)
                end = datetime.now()
                assert msg.decode() == "processed write request"

                res = fut.result()
                request_id = res.output["request_id"]
                is_cold = 1 if res.output["is_cold"] else 0
                writer.writerow([i, is_cold,  begin.timestamp(), end.timestamp(), request_id])

    def warm_invocation(self):
        settings = self.config.experiment_settings(self.name())
        port = settings['local-port']
        repetitions = settings["repetitions"]
        input_benchmark = {
            "caller-address": self.ip,
            "caller-port": port,
            "holepunching-address": settings["holepunching-address"],
            "holepunching-port": settings["holepunching-port"],
            "keep-alive-time": 0,
            "function-id": str(uuid.uuid4())[0:8],
            **self.benchmark_input,
        }

        output_file = os.path.join(self._out_dir, "warm_invocation.csv")
        with open(output_file, "w") as csvfile:
            writer = csv.writer(csvfile, delimiter=",")
            writer.writerow(
                [
                    "repetition",
                    "is_cold",
                    "start_timestamp",
                    "receive_timestamp",
                    "request_id",
                ]
            )
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind(('', port))

            fut = self._trigger.async_invoke(input_benchmark)
            for i in range(repetitions):
                print(f"Starting with repetition {i}")

                begin = datetime.now()
                fut = self._trigger.async_invoke(input_benchmark)
                msg, addr = server_socket.recvfrom(1024)
                end = datetime.now()
                assert msg.decode() == "processed write request"

                res = fut.result()
                request_id = res.output["request_id"]
                is_cold = 1 if res.output["is_cold"] else 0
                writer.writerow([i, is_cold,  begin.timestamp(), end.timestamp(), request_id])

    def cold_access(self):
        settings = self.config.experiment_settings(self.name())
        port = settings['local-port']
        repetitions = settings["repetitions"]
        input_benchmark = {
            "caller-address": self.ip,
            "caller-port": port,
            "holepunching-address": settings["holepunching-address"],
            "holepunching-port": settings["holepunching-port"],
            "keep-alive-time": 5,
            "function-id": str(uuid.uuid4())[0:8],
            **self.benchmark_input,
        }
        holepuncher_addr = (settings["holepunching-address"], settings["holepunching-port"])
        holepuncher_request = json.dumps({"type": "connect", "id": input_benchmark["function-id"]}).encode()
        write_request = json.dumps({"type": "request"}).encode()

        output_file = os.path.join(self._out_dir, "cold_access.csv")
        with open(output_file, "w") as csvfile:
            writer = csv.writer(csvfile, delimiter=",")
            writer.writerow(
                [
                    "repetition",
                    "start_timestamp",
                    "holepuncher_timestamp",
                    "receive_timestamp",
                ]
            )
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind(('', port))
            fut = self._trigger.async_invoke(input_benchmark)
            msg, addr = server_socket.recvfrom(1024)
            assert msg.decode() == "processed write request"


            for i in range(repetitions):
                print(f"Starting with repetition {i}")

                begin = datetime.now()
                server_socket.sendto(holepuncher_request, holepuncher_addr)
                message_holepuncher, _ = server_socket.recvfrom(1024)
                holepuncher_stamp = datetime.now()
                address_function = tuple(json.loads(message_holepuncher.decode())['addr'])
                
                # wait for punching
                server_socket.recvfrom(1024)
                server_socket.sendto(write_request, address_function)
                msg, addr = server_socket.recvfrom(1024)
                end = datetime.now()
                assert msg.decode() == "processed write request"

                writer.writerow([i, begin.timestamp(), holepuncher_stamp.timestamp(), end.timestamp()])
        fut.result()

    def warm_access(self):
        settings = self.config.experiment_settings(self.name())
        port = settings['local-port']
        repetitions = settings["repetitions"]
        input_benchmark = {
            "caller-address": self.ip,
            "caller-port": port,
            "holepunching-address": settings["holepunching-address"],
            "holepunching-port": settings["holepunching-port"],
            "keep-alive-time": 5,
            "function-id": str(uuid.uuid4())[0:8],
            **self.benchmark_input,
        }
        holepuncher_addr = (settings["holepunching-address"], settings["holepunching-port"])
        holepuncher_request = json.dumps({"type": "connect", "id": input_benchmark["function-id"]}).encode()
        write_request = json.dumps({"type": "request"}).encode()

        output_file = os.path.join(self._out_dir, "warm_access.csv")
        with open(output_file, "w") as csvfile:
            writer = csv.writer(csvfile, delimiter=",")
            writer.writerow(
                [
                    "repetition",
                    "start_timestamp",
                    "receive_timestamp",
                ]
            )
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind(('', port))
            fut = self._trigger.async_invoke(input_benchmark)
            msg, addr = server_socket.recvfrom(1024)
            assert msg.decode() == "processed write request"
            server_socket.sendto(holepuncher_request, holepuncher_addr)
            message_holepuncher, _ = server_socket.recvfrom(1024)
            response_holepuncher = json.loads(message_holepuncher.decode())
            while response_holepuncher["state"] == "NOT_OK":
                server_socket.sendto(holepuncher_request, holepuncher_addr)
                message_holepuncher, _ = server_socket.recvfrom(1024)
                response_holepuncher = tuple(json.loads(message_holepuncher.decode()))
            address_function = tuple(response_holepuncher['addr'])
            # receive hole punching packet
            msg, addr = server_socket.recvfrom(1024)

            for i in range(repetitions):
                print(f"Starting with repetition {i} on func {address_function}")

                begin = datetime.now()                
                write_request = json.dumps({"type": "request", "id": i}).encode()
                #print(f"send {write_request}")
                server_socket.sendto(write_request, address_function)
                msg, addr = server_socket.recvfrom(1024)
                end = datetime.now()
                assert msg.decode() == "processed write request"
                writer.writerow([i, begin.timestamp(), end.timestamp()])

        fut.result()

    def run(self):
        self.cold_invocation()
        self.warm_invocation()
        self.cold_access()
        self.warm_access()

    def process(self, directory: str):
        import pandas as pd
        for f in ["cold_invocation.csv", "warm_invocation.csv", "cold_access.csv", "warm_access.csv"]:
            with open(os.path.join(directory, self.name(), f)) as f:
                df = pd.read_csv(f, sep=",")
                df['time'] = df['receive_timestamp'] - df['start_timestamp']
                print(f)
                print('Rows: ', df.shape[0])
                print('Mean: ', df['time'].mean())
                print('STD: ', df['time'].std())
                print('CV: ', df['time'].std() / df['time'].mean())
                print('P50: ', df['time'].quantile(0.5))
                print('P75: ', df['time'].quantile(0.75))
                print('P95: ', df['time'].quantile(0.95))
                print('P99: ', df['time'].quantile(0.99))
                print('P99,9: ', df['time'].quantile(0.999))

    @staticmethod
    def name() -> str:
        return "service-access-latency"

    @staticmethod
    def typename() -> str:
        return "Experiment.ServiceAccessLatency"
