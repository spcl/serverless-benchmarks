import csv
import os
import random
import time
from datetime import datetime
from typing import Dict, TYPE_CHECKING

from sebs.benchmark import Benchmark
from sebs.faas.system import System as FaaSSystem
from sebs.experiments.experiment import Experiment
from sebs.experiments.config import Config as ExperimentConfig

if TYPE_CHECKING:
    from sebs import SeBS


class CodePackageSize:
    """
    Helper class to manage code package size variations for the InvocationOverhead experiment.

    Generates different code package sizes by creating a file with random data.
    """
    def __init__(self, deployment_client: FaaSSystem, benchmark: Benchmark, settings: dict):
        """
        Initialize CodePackageSize.

        Calculates target points for code package sizes based on experiment settings.

        :param deployment_client: FaaS system client for function updates.
        :param benchmark: The benchmark object to modify.
        :param settings: Dictionary of experiment settings, expected to contain:
                         'code_package_begin', 'code_package_end', 'code_package_points'.
        """
        import math
        from numpy import linspace

        points = linspace(
            settings["code_package_begin"],
            settings["code_package_end"],
            settings["code_package_points"],
        )
        from sebs.utils import find_benchmark

        self._benchmark_path = find_benchmark("030.clock-synchronization", "benchmarks")
        self._benchmark = benchmark
        random.seed(1410)

        # estimate the size after zip compression
        self.pts = [int(pt) - 4 * 1024 for pt in points]
        self.pts = [math.floor((pt - 123) * 3 / 4) for pt in points]

        self._deployment_client = deployment_client
        self._benchmark = benchmark

    def before_sample(self, size: int, input_benchmark: dict):
        """
        Modify the benchmark's code package to achieve the target size and update the function.

        Creates a file named 'randomdata.bin' with the specified size of random bytes
        within the benchmark's code package. Then, updates the function on the deployment.

        :param size: The target size of the random data file in bytes.
        :param input_benchmark: Not directly used but part of a common interface.
        """
        arr = bytearray((random.getrandbits(8) for i in range(size)))
        self._benchmark.code_package_modify("randomdata.bin", bytes(arr))
        function = self._deployment_client.get_function(self._benchmark)
        self._deployment_client.update_function(function, self._benchmark, False, "")


class PayloadSize:
    """
    Helper class to manage payload size variations for the InvocationOverhead experiment.

    Generates different payload sizes by creating base64 encoded byte arrays.
    """
    def __init__(self, settings: dict):
        """
        Initialize PayloadSize.

        Calculates target points for payload sizes based on experiment settings.

        :param settings: Dictionary of experiment settings, expected to contain:
                         'payload_begin', 'payload_end', 'payload_points'.
        """
        from numpy import linspace

        points = linspace(
            settings["payload_begin"],
            settings_["payload_end"],
            settings["payload_points"],
        )
        self.pts = [int(pt) for pt in points]

    def before_sample(self, size: int, input_benchmark: dict):
        """
        Modify the input benchmark dictionary to include data of the target size.

        Creates a base64 encoded string of a byte array of the specified size
        and adds it to the `input_benchmark` dictionary under the key 'data'.

        :param size: The target size of the byte array before base64 encoding.
        :param input_benchmark: The dictionary to modify with the new payload data.
        """
        import base64
        from io import BytesIO

        f = BytesIO()
        f.write(bytearray(size))
        input_benchmark["data"] = base64.b64encode(f.getvalue()).decode()


class InvocationOverhead(Experiment):
    """
    Experiment to measure invocation overhead by varying code package size or payload size.

    Uses the '030.clock-synchronization' benchmark to establish a baseline and then
    measures how changes in code/payload size affect invocation times.
    """
    def __init__(self, config: ExperimentConfig):
        """
        Initialize the InvocationOverhead experiment.

        :param config: Experiment configuration.
        """
        super().__init__(config)
        self.settings = self.config.experiment_settings(self.name())

    def prepare(self, sebs_client: "SeBS", deployment_client: FaaSSystem):
        """
        Prepare the experiment environment.

        Deploys the '030.clock-synchronization' benchmark, prepares its input,
        and sets up necessary triggers and output directories.

        :param sebs_client: The SeBS client instance.
        :param deployment_client: The FaaS system client.
        """
        # deploy network test function
        from sebs import SeBS  # noqa
        from sebs.faas.function import Trigger

        self._benchmark = sebs_client.get_benchmark(
            "030.clock-synchronization", deployment_client, self.config
        )

        self.benchmark_input = self._benchmark.prepare_input(
            deployment_client.system_resources, size="test", replace_existing=True
        )
        self._storage = deployment_client.system_resources.get_storage(replace_existing=True)

        self._function = deployment_client.get_function(self._benchmark)

        triggers = self._function.triggers(Trigger.TriggerType.HTTP)
        if len(triggers) == 0:
            self._trigger = deployment_client.create_trigger(
                self._function, Trigger.TriggerType.HTTP
            )
        else:
            self._trigger = triggers[0]

        self._out_dir = os.path.join(
            sebs_client.output_dir, "invocation-overhead", self.settings["type"]
        )
        if not os.path.exists(self._out_dir):
            os.makedirs(self._out_dir)

        self._deployment_client = deployment_client

    def run(self):
        """
        Run the InvocationOverhead experiment.

        Iterates through different sizes (either code package or payload, based on settings)
        and repetitions, invoking the function and recording timing data.
        Results, including client-side and server-side timestamps, are saved to CSV files.
        """
        from requests import get

        ip = get("http://checkip.amazonaws.com/").text.rstrip()
        repetitions = self.settings["repetitions"]
        N = self.settings["N"]

        if self.settings["type"] == "code":
            experiment = CodePackageSize(self._deployment_client, self._benchmark, self.settings)
        else:
            experiment = PayloadSize(self.settings)

        input_benchmark = {
            "server-address": ip,
            "repetitions": N,
            **self.benchmark_input,
        }

        output_file = os.path.join(self._out_dir, "result.csv")
        with open(output_file, "w") as csvfile:
            writer = csv.writer(csvfile, delimiter=",")
            writer.writerow(
                [
                    "size",
                    "repetition",
                    "is_cold",
                    "connection_time",
                    "start_timestamp",
                    "finish_timestamp",
                    "request_id",
                ]
            )

            for result_type in ["warm", "cold"]:
                # warm up
                if result_type == "warm":
                    self.logging.info("Warm up invocation!")
                    self.receive_datagrams(input_benchmark, N, 12000, ip)
                for size in experiment.pts:
                    experiment.before_sample(size, input_benchmark)

                    for i in range(repetitions):
                        succesful = False
                        while not succesful:
                            self.logging.info(f"Starting with {size} bytes, repetition {i}")
                            if result_type == "cold":
                                self._deployment_client.enforce_cold_start(
                                    [self._function], self._benchmark
                                )
                                time.sleep(1)
                            row = self.receive_datagrams(input_benchmark, N, 12000, ip)
                            if result_type == "cold":
                                if not row[0]:
                                    self.logging.info("Not cold!")
                                    continue
                            else:
                                if row[0]:
                                    self.logging.info("cold!")
                                    continue
                            writer.writerow([size, i] + row)
                            succesful = True

        time.sleep(5)
        self._storage.download_bucket(self.benchmark_input["output-bucket"], self._out_dir)

    def process(
        self,
        sebs_client: "SeBS",
        deployment_client,
        directory: str,
        logging_filename: str,
        extend_time_interval: int,
    ):
        """
        Process the raw results from the InvocationOverhead experiment.

        Reads client-side timing data and server-side UDP datagram timestamps,
        calculates Round-Trip Time (RTT) and clock drift, and then computes
        the adjusted invocation time. Processed results are saved to
        'result-processed.csv'.

        :param sebs_client: The SeBS client instance.
        :param deployment_client: The FaaS system client (not directly used in this method).
        :param directory: The main output directory for SeBS results.
        :param logging_filename: (Not used in this method).
        :param extend_time_interval: (Not used in this method).
        """
        import pandas as pd
        import glob
        from sebs import SeBS  # noqa

        experiment_out_dir = os.path.join(directory, "invocation-overhead", self.settings["type"])
        full_data: Dict[str, pd.DataFrame] = {} # Changed type hint for clarity
        # Process server-side datagram files (e.g., server-request_id.csv)
        for f_path in glob.glob(os.path.join(experiment_out_dir, "server-*.csv")):
            if "result.csv" in f_path or "result-processed.csv" in f_path: # Original had `f`
                continue
            request_id = os.path.basename(f_path).split("-", 1)[1].split(".")[0]
            data = pd.read_csv(f_path, sep=",").drop(["id"], axis=1) # Assuming 'id' is datagram sequence
            # It seems like the original logic for concatenating might be incorrect if multiple
            # files per request_id are not expected or if they have different structures.
            # Assuming here that each server-*.csv is self-contained for its request_id's datagrams.
            # If merging is needed, the logic would depend on the structure of these files.
            # For now, let's assume data for a request_id is processed together.
            # If `full_data` was meant to merge client and server data, that needs different handling.
            # The original code seems to build `full_data` from server files only, then uses it with client file.
            # This suggests `full_data` should be a DataFrame directly.
            # Let's simplify: assume we process server files to get clock drift per request_id.
            # This part of the original code seems to build a DataFrame `df` from all server files.
            if request_id not in full_data:
                full_data[request_id] = data
            else:
                # This concatenation implies server-*.csv files might be split, which is unusual.
                # Or it means one request_id can have multiple such files (e.g. from retries).
                # Sticking to original logic for now.
                full_data[request_id] = pd.concat([full_data[request_id], data], axis=0) # Changed to axis=0 for row-wise concat

        # Create a single DataFrame from all server-side datagram data
        if not full_data:
            self.logging.warning(f"No server datagram files found in {experiment_out_dir}. Cannot process clock drift.")
            return
        df_all_server_data = pd.concat(full_data.values(), keys=full_data.keys(), names=['request_id_level', 'original_index']).reset_index()
        df_all_server_data.rename(columns={'request_id_level': 'id'}, inplace=True) # 'id' now means request_id

        # Calculate RTT and clock drift for each datagram
        df_all_server_data["rtt"] = (df_all_server_data["server_rcv"] - df_all_server_data["client_send"]) + \
                                    (df_all_server_data["client_rcv"] - df_all_server_data["server_send"])
        df_all_server_data["clock_drift"] = (
            (df_all_server_data["client_send"] - df_all_server_data["server_rcv"]) +
            (df_all_server_data["client_rcv"] - df_all_server_data["server_send"])
        ) / 2

        # Aggregate clock drift per request_id
        clock_drift_stats = df_all_server_data.groupby('id')['clock_drift'].agg(['mean', 'std']).reset_index()
        clock_drift_stats.rename(columns={'mean': 'clock_drift_mean', 'std': 'clock_drift_std'}, inplace=True)

        # Process the main client-side result file
        client_result_file = os.path.join(experiment_out_dir, "result.csv")
        processed_client_result_file = os.path.join(experiment_out_dir, "result-processed.csv")

        try:
            df_client = pd.read_csv(client_result_file)
        except FileNotFoundError:
            self.logging.error(f"Client result file not found: {client_result_file}")
            return

        # Merge client results with clock drift stats
        df_merged = pd.merge(df_client, clock_drift_stats, on="request_id", how="left")

        # Calculate invocation time adjusted for clock drift
        # invocation_time = server_timestamp - client_start_timestamp - connection_time + clock_drift
        df_merged["invocation_time"] = (df_merged["finish_timestamp"] -
                                        df_merged["start_timestamp"] -
                                        df_merged["connection_time"] +
                                        df_merged["clock_drift_mean"])

        # Save the processed data
        output_columns = [
            "size", # 'payload_size' in original, but 'size' in the client data writer
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
        # Ensure all columns exist, fill with NaN if not (e.g. if clock_drift stats are missing for a request_id)
        for col in output_columns:
            if col not in df_merged.columns:
                df_merged[col] = pd.NA

        df_merged.to_csv(processed_client_result_file, columns=output_columns, index=False, na_rep='NaN')
        self.logging.info(f"Processed results saved to {processed_client_result_file}")

    def receive_datagrams(self, input_benchmark: dict, repetitions: int, port: int, ip: str) -> list:
        """
        Receive UDP datagrams from the invoked function for clock synchronization.

        Opens a UDP socket, triggers an asynchronous function invocation, and then
        listens for a specified number of datagrams. Records timestamps for
        received and sent datagrams. Saves server-side timestamps to a CSV file
        named `server-{request_id}.csv`.

        :param input_benchmark: The input payload for the benchmark function.
                                Will be modified with 'server-port'.
        :param repetitions: The number of datagrams expected from the function.
        :param port: The local port number to bind the UDP socket to.
        :param ip: (Not directly used in this function, but part of the calling context).
        :return: A list containing: [is_cold (int), connection_time (float),
                 client_begin_timestamp (float), server_timestamp (float from function output),
                 request_id (str)].
        :raises RuntimeError: If the function invocation fails.
        """
        import socket

        input_benchmark["server-port"] = port
        self.logging.info(f"Starting invocation with {repetitions} repetitions on port {port}")
        socket.setdefaulttimeout(4)
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server_socket.bind(("", port))

        fut = self._trigger.async_invoke(input_benchmark)

        begin = datetime.now()
        times = []
        i = 0
        j = 0
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
                self.logging.warning("Packet loss!")
                # stop after 5 attempts
                if j == 5:
                    self.logging.error(
                        "Failing after 5 unsuccesfull attempts to " "communicate with the function!"
                    )
                    break
                # check if function invocation failed, and if yes: raise the exception
                if fut.done():
                    raise RuntimeError("Function invocation failed") from None
                # continue to next iteration
                continue
            if i > 0:
                times.append([i, timestamp_rcv, timestamp_send])
            i += 1
            j += 1
        end = datetime.now()

        # Save results even in case of failure - it might have happened in n-th iteration
        res = fut.result()
        server_timestamp = res.output["result"]["output"]["timestamp"]
        request_id = res.output["request_id"]
        is_cold = 1 if res.output["is_cold"] else 0
        output_file = os.path.join(self._out_dir, f"server-{request_id}.csv")
        with open(output_file, "w") as csvfile:
            writer = csv.writer(csvfile, delimiter=",")
            writer.writerow(["id", "server_rcv", "server_send"])
            for row in times:
                writer.writerow(row)

        self.logging.info(f"Finished {request_id} in {end - begin} [s]")

        return [
            is_cold,
            res.times.http_startup,
            res.times.client_begin.timestamp(),
            server_timestamp,
            request_id,
        ]

    @staticmethod
    def name() -> str:
        """Return the name of the experiment."""
        return "invocation-overhead"

    @staticmethod
    def typename() -> str:
        """Return the type name of this experiment class."""
        return "Experiment.InvocOverhead"
