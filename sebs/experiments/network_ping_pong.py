"""Network latency and throughput measurement experiment implementation.

This module provides the NetworkPingPong experiment implementation, which
measures network latency and throughput characteristics between client and
serverless functions. It determines various latency characteristics of the network
connection in the cloud.
"""

import csv
import socket
import os
import time
import glob
import pandas as pd
from datetime import datetime
from itertools import repeat
from typing import Dict, TYPE_CHECKING
from multiprocessing.dummy import Pool as ThreadPool

from sebs.faas.system import System as FaaSSystem
from sebs.faas.function import Trigger
from sebs.experiments.experiment import Experiment
from sebs.experiments.config import Config as ExperimentConfig

# import cycle
if TYPE_CHECKING:
    from sebs import SeBS


class NetworkPingPong(Experiment):
    """Network latency and throughput measurement experiment.

    This experiment measures the network RTT (Round-Trip Time) using a ping-pong mechanism.
    Deploys the '020.network-benchmark' which echoes back UDP datagrams.
    The experiment sends a series of datagrams and measures the time taken
    for each to return. This experiment measures the network performance characteristics
    between the client and serverless functions.


    Attributes:
        benchmark_input: Input configuration for the benchmark
        _storage: Storage service to use for testing
        _function: Function to invoke
        _triggers: Dictionary of triggers by type
        _out_dir: Directory for storing results
        _deployment_client: Deployment client to use
        _sebs_client: SeBS client
    """

    def __init__(self, config: ExperimentConfig):
        """Initialize a new NetworkPingPong experiment.

        Args:
            config: Experiment configuration
        """
        super().__init__(config)

    def prepare(self, sebs_client: "SeBS", deployment_client: FaaSSystem) -> None:
        """Prepare the experiment for execution.

        This method sets up the '020.network-benchmark' benchmark, triggers, storage,
        and output directory for the experiment. It creates or gets the function and
        its HTTP trigger, and prepares the input data for the benchmark.

        Args:
            sebs_client: The SeBS client to use
            deployment_client: The deployment client to use
        """
        # Get the network benchmark
        benchmark = sebs_client.get_benchmark(
            "020.network-benchmark", deployment_client, self.config
        )

        # Prepare benchmark input
        self.benchmark_input = benchmark.prepare_input(
            deployment_client.system_resources, size="test", replace_existing=True
        )

        # Get storage for testing storage latency
        self._storage = deployment_client.system_resources.get_storage(replace_existing=True)

        # Get or create function
        self._function = deployment_client.get_function(benchmark)

        # Create output directory
        self._out_dir = os.path.join(sebs_client.output_dir, "network-ping-pong")
        if not os.path.exists(self._out_dir):
            # shutil.rmtree(self._out_dir)
            os.mkdir(self._out_dir)

        # Make sure there's an HTTP trigger
        triggers = self._function.triggers(Trigger.TriggerType.HTTP)
        if len(triggers) == 0:
            deployment_client.create_trigger(self._function, Trigger.TriggerType.HTTP)

    def run(self) -> None:
        """Run the network ping-pong experiment.

        This method executes the experiment, measuring network latency and
        throughput between the client and the serverless function. It first
        determines the client's public IP address to include in the results.
        """
        from requests import get

        # Get the client's public IP address
        ip = get("http://checkip.amazonaws.com/").text.rstrip()
        settings = self.config.experiment_settings(self.name())
        invocations = settings["invocations"]
        repetitions = settings["repetitions"]
        threads = settings["threads"]

        pool = ThreadPool(threads)
        ports = range(12000, 12000 + invocations)
        pool.starmap(
            self.receive_datagrams,
            zip(repeat(repetitions, invocations), ports, repeat(ip, invocations)),
        )

        # give functions time to finish and upload result
        time.sleep(5)
        self._storage.download_bucket(self.benchmark_input["output-bucket"], self._out_dir)

    def process(self, directory: str) -> None:
        """Process the experiment results.

        This method processes the CSV files generated during the experiment
        execution, computes round-trip times (RTT), and generates summary
        statistics and a histogram of the RTT distribution.

        Args:
            directory: Directory containing the experiment results
        """
        full_data: Dict[str, pd.DataFrame] = {}
        for f in glob.glob(os.path.join(directory, "network-ping-pong", "*.csv")):

            request_id = os.path.basename(f).split("-", 1)[1].split(".")[0]
            data = pd.read_csv(f, sep=",").drop(["id"], axis=1)
            if request_id in full_data:
                full_data[request_id] = pd.concat([full_data[request_id], data], axis=1)
            else:
                full_data[request_id] = data
        df = pd.concat(full_data.values()).reset_index(drop=True)
        df["rtt"] = (df["server_rcv"] - df["client_send"]) + (df["client_rcv"] - df["server_send"])
        print("Rows: ", df.shape[0])
        print("Mean: ", df["rtt"].mean())
        print("STD: ", df["rtt"].std())
        print("CV: ", df["rtt"].std() / df["rtt"].mean())
        print("P50: ", df["rtt"].quantile(0.5))
        print("P75: ", df["rtt"].quantile(0.75))
        print("P95: ", df["rtt"].quantile(0.95))
        print("P99: ", df["rtt"].quantile(0.99))
        print("P99,9: ", df["rtt"].quantile(0.999))
        ax = df["rtt"].hist(bins=2000)
        # ax.set_xlim([0.01, 0.04])
        fig = ax.get_figure()
        fig.savefig(os.path.join(directory, "histogram.png"))

    def receive_datagrams(self, repetitions: int, port: int, ip: str) -> None:
        """Receive UDP datagrams from the function and respond to them.

        This method acts as a UDP server, receiving datagrams from the function
        and responding to them. It measures the timestamps of packet reception
        and response, and records them for later analysis.

        Args:
            repetitions: Number of repetitions to execute
            port: UDP port to listen on
            ip: IP address to include in the function invocation input
        """
        print(f"Starting invocation with {repetitions} repetitions on port {port}")
        socket.setdefaulttimeout(2)
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server_socket.bind(("", port))

        input_benchmark = {
            "server-address": ip,
            "server-port": port,
            "repetitions": repetitions,
            **self.benchmark_input,
        }
        self._function.triggers(Trigger.TriggerType.HTTP)[0].async_invoke(input_benchmark)

        begin = datetime.now()
        times = []
        i = 0
        j = 0
        update_counter = int(repetitions / 10)
        while i < repetitions + 1:
            try:
                message, address = server_socket.recvfrom(1024)
                timestamp_rcv = datetime.now().timestamp()
                timestamp_send = datetime.now().timestamp()
                server_socket.sendto(message, address)
            except socket.timeout:
                i += 1
                print("Packet loss!")
                continue
            if i > 0:
                times.append([i, timestamp_rcv, timestamp_send])
            if j == update_counter:
                print(f"Invocation on port {port} processed {i} requests.")
                j = 0
            i += 1
            j += 1
        request_id = message.decode()
        end = datetime.now()
        print(f"Finished {request_id} in {end - begin} [s]")

        output_file = os.path.join(self._out_dir, f"server-{request_id}.csv")
        with open(output_file, "w") as csvfile:
            writer = csv.writer(csvfile, delimiter=",")
            writer.writerow(["id", "server_rcv", "server_send"])
            for row in times:
                writer.writerow(row)

    @staticmethod
    def name() -> str:
        """Get the name of the experiment.

        Returns:
            The name "network-ping-pong"
        """
        return "network-ping-pong"

    @staticmethod
    def typename() -> str:
        """Get the type name of the experiment.

        Returns:
            The type name "Experiment.NetworkPingPong"
        """
        return "Experiment.NetworkPingPong"
