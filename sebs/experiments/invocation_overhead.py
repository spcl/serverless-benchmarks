import csv
import os
import shutil
from datetime import datetime
from itertools import repeat
from multiprocessing.dummy import Pool as ThreadPool

from sebs.faas.system import System as FaaSSystem
from sebs.experiments.experiment import Experiment
from sebs.experiments.config import Config as ExperimentConfig


class InvocationOverhead(Experiment):
    def __init__(self, config: ExperimentConfig):
        super().__init__(config)

    def prepare(self, sebs_client: "SeBS", deployment_client: FaaSSystem):

        # deploy network test function
        from sebs import Benchmark
        from sebs import SeBS

        benchmark = sebs_client.get_benchmark(
            "030.clock-synchronization", deployment_client, self.config
        )
        self._benchmark = benchmark
        self._function = deployment_client.get_function(benchmark)

        # TODO: Azure -> no trigger creation; get HTTP trigger
        # if len(self._function.triggers) == 1:
        #    from sebs.faas.function import Trigger
        #    deployment_client.create_trigger(self._function, Trigger.TriggerType.HTTP)

        self._storage = deployment_client.get_storage(replace_existing=True)
        self.benchmark_input = benchmark.prepare_input(
            storage=self._storage, size="test"
        )
        self._out_dir = os.path.join(sebs_client.output_dir, "invocation-overhead")
        if not os.path.exists(self._out_dir):
            # shutil.rmtree(self._out_dir)
            os.mkdir(self._out_dir)

        self._deployment_client = deployment_client

    def run(self):

        from requests import get

        ip = get("http://checkip.amazonaws.com/").text.rstrip()
        settings = self.config.experiment_settings(self.name())
        invocations = settings["invocations"]
        repetitions = settings["repetitions"]
        N = settings["N"]
        threads = settings["threads"]
        begin_payload_size = settings["payload_begin"]
        end_payload_size = settings["payload_end"]
        payload_pts = settings["payload_points"]

        input_benchmark = {
            "server-address": ip,
            "repetitions": N,
            **self.benchmark_input,
        }
        from io import BytesIO
        import base64, math, json

        output_file = os.path.join(self._out_dir, "result.csv")
        with open(output_file, "w") as csvfile:
            writer = csv.writer(csvfile, delimiter=",")
            writer.writerow(
                [
                    "payload_size",
                    "repetition",
                    "is_cold",
                    "connection_time",
                    "start_timestamp",
                    "finish_timestamp",
                    "request_id",
                ]
            )

            from numpy import linspace

            pts = linspace(begin_payload_size, end_payload_size, payload_pts)
            for pt in pts:
                print(pt)
                size = int(pt) - 4 * 1024
                print(size)
                arr = bytearray((random.getrandbits(8) for i in range(size)))
                from sebs.utils import find_benchmark

                benchmark_path = find_benchmark(
                    "030.clock-synchronization", "benchmarks"
                )
                with open(os.path.join(benchmark_path, "python", "file.py"), "wb") as f:
                    f.write(arr)
                self._benchmark.query_cache()
                self._function = self._deployment_client.get_function(self._benchmark)

                # print(json.dumps(input_benchmark))
                for i in range(repetitions + 1):
                    print(f"Starting with {pt} bytes, repetition {i}")
                    self._deployment_client.update_function(
                        self._function, self._benchmark
                    )
                    # self._deployment_client.enforce_cold_start(self._function)
                    # self._deployment_client.enforce_cold_start(self._function, self._benchmark)
                    row = self.receive_datagrams(input_benchmark, N, 12000, ip)
                    writer.writerow([pt, i] + row)

        # pool = ThreadPool(threads)
        # ports = range(12000, 12000 + invocations)
        # ret = pool.starmap(self.receive_datagrams,
        #    zip(repeat(repetitions, invocations), ports, repeat(ip, invocations))
        # )
        # requests = []
        # for val in ret:
        #    print(val)
        import time

        time.sleep(5)
        self._storage.download_bucket(
            self.benchmark_input["output-bucket"], self._out_dir
        )

    def process(self, directory: str):

        import pandas as pd
        import glob

        full_data = {}
        for f in glob.glob(os.path.join(directory, "invocation-overhead", "*.csv")):

            if "result.csv" in f or "result-processed.csv" in f:
                continue
            request_id = os.path.basename(f).split("-", 1)[1].split(".")[0]
            data = pd.read_csv(f, sep=",").drop(["id"], axis=1)
            if request_id in full_data:
                full_data[request_id] = pd.concat([full_data[request_id], data], axis=1)
                full_data[request_id]["id"] = request_id
            else:
                full_data[request_id] = data
        df = pd.concat(full_data.values()).reset_index(drop=True)
        df["rtt"] = (df["server_rcv"] - df["client_send"]) + (
            df["client_rcv"] - df["server_send"]
        )
        df["clock_drift"] = (
            (df["client_send"] - df["server_rcv"])
            + (df["client_rcv"] - df["server_send"])
        ) / 2
        print(df)

        with open(
            os.path.join(directory, "invocation-overhead", "result.csv")
        ) as csvfile:
            with open(
                os.path.join(directory, "invocation-overhead", "result-processed.csv"),
                "w",
            ) as csvfile2:
                reader = csv.reader(csvfile, delimiter=",")
                writer = csv.writer(csvfile2, delimiter=",")
                writer.writerow(
                    [
                        "payload_size",
                        "repetition",
                        "is_cold",
                        "connection_time",
                        "start_timestamp",
                        "finish_timestamp",
                        "request_id",
                        "clock_drift_mean",
                        "clock_drift_std",
                        "invocation_time",
                    ]
                )
                iter2 = iter(reader)
                next(iter2)
                for row in iter2:
                    # print(row)
                    request_id = row[-1]
                    # print(request_id)
                    # clock_drift = df[df['id'] == request_id]
                    clock_drift = df[df["id"] == request_id]["clock_drift"].mean()
                    clock_drift_std = df[df["id"] == request_id]["clock_drift"].std()
                    invocation_time = (
                        float(row[5]) - float(row[4]) - float(row[3]) + clock_drift
                    )
                    writer.writerow(
                        row + [clock_drift, clock_drift_std, invocation_time]
                    )

        # df['rtt'] = (df['server_rcv'] - df['client_send']) + (df['client_rcv'] - df['server_send'])
        # print('Rows: ', df.shape[0])
        # print('Mean: ', df['rtt'].mean())
        # print('STD: ', df['rtt'].std())
        # print('CV: ', df['rtt'].std() / df['rtt'].mean())
        # print('P50: ', df['rtt'].quantile(0.5))
        # print('P75: ', df['rtt'].quantile(0.75))
        # print('P95: ', df['rtt'].quantile(0.95))
        # print('P99: ', df['rtt'].quantile(0.99))
        # print('P99,9: ', df['rtt'].quantile(0.999))
        # ax = df['rtt'].hist(bins=2000)
        ##ax.set_xlim([0.01, 0.04])
        # fig = ax.get_figure()
        # fig.savefig(os.path.join(directory, 'histogram.png'))

    def receive_datagrams(
        self, input_benchmark: dict, repetitions: int, port: int, ip: str
    ):

        import socket

        input_benchmark["server-port"] = port
        print(f"Starting invocation with {repetitions} repetitions on port {port}")
        socket.setdefaulttimeout(4)
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server_socket.bind(("", port))

        # TODO: tirgger 1 for AWS
        # fut = self._function.triggers[1].async_invoke(input_benchmark)
        fut = self._function.triggers[0].async_invoke(input_benchmark)

        begin = datetime.now()
        times = []
        i = 0
        j = 0
        update_counter = int(repetitions / 10)
        while True:
            try:
                message, address = server_socket.recvfrom(1024)
                timestamp_rcv = datetime.now().timestamp()
                if message.decode() == "stop":
                    break
                timestamp_send = datetime.now().timestamp()
                server_socket.sendto(message, address)
                j = 0
            except socket.timeout:
                j += 1
                print("Packet loss!")
                if j == 5:
                    break
                continue
            if i > 0:
                times.append([i, timestamp_rcv, timestamp_send])
            # if j == update_counter:
            #    print(f"Invocation on port {port} processed {i} requests.")
            #    j = 0
            i += 1
            j += 1
        # request_id = message.decode()
        end = datetime.now()

        res, conn_time, client_timestamp = fut.result()
        server_timestamp = res.output["result"]["result"]["timestamp"]
        request_id = res.output["request_id"]
        is_cold = 1 if res.output["is_cold"] else 0
        output_file = os.path.join(self._out_dir, f"server-{request_id}.csv")
        with open(output_file, "w") as csvfile:
            writer = csv.writer(csvfile, delimiter=",")
            writer.writerow(["id", "server_rcv", "server_send"])
            for row in times:
                writer.writerow(row)

        print(f"Finished {request_id} in {end - begin} [s]")
        # print(conn_time)

        return [
            is_cold,
            conn_time,
            client_timestamp.timestamp(),
            server_timestamp,
            request_id,
        ]

    @staticmethod
    def name() -> str:
        return "invocation-overhead"

    @staticmethod
    def typename() -> str:
        return "Experiment.InvocOverhead"
