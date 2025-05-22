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
    """
    Experiment to measure network RTT (Round-Trip Time) using a ping-pong mechanism.

    Deploys the '020.network-benchmark' which typically involves a function that
    echoes back UDP datagrams. The experiment sends a series of datagrams and
    measures the time taken for each to return.
    """
    def __init__(self, config: ExperimentConfig):
        """
        Initialize the NetworkPingPong experiment.

        :param config: Experiment configuration.
        """
        super().__init__(config)

    def prepare(self, sebs_client: "SeBS", deployment_client: FaaSSystem):
        """
        Prepare the experiment environment.

        Deploys the '020.network-benchmark', prepares its input,
        and ensures an HTTP trigger is available for the function.
        Sets up the output directory for results.

        :param sebs_client: The SeBS client instance.
        :param deployment_client: The FaaS system client.
        """
        benchmark = sebs_client.get_benchmark(
            "020.network-benchmark", deployment_client, self.config
        )

        self.benchmark_input = benchmark.prepare_input(
            deployment_client.system_resources, size="test", replace_existing=True
        )
        self._storage = deployment_client.system_resources.get_storage(replace_existing=True)

        self._function = deployment_client.get_function(benchmark)

        self._out_dir = os.path.join(sebs_client.output_dir, "network-ping-pong")
        if not os.path.exists(self._out_dir):
            # shutil.rmtree(self._out_dir)
            os.mkdir(self._out_dir)

        triggers = self._function.triggers(Trigger.TriggerType.HTTP)
        if len(triggers) == 0:
            # Assuming create_trigger returns the created trigger,
            # though it's not explicitly used later in this prepare method.
            deployment_client.create_trigger(self._function, Trigger.TriggerType.HTTP)

    def run(self):
        """
        Run the NetworkPingPong experiment.

        Retrieves the public IP, then starts multiple threads (based on 'threads'
        setting) each running `receive_datagrams` for a number of invocations
        (based on 'invocations' setting) on different ports.
        After all threads complete, downloads benchmark output from storage.
        """
        from requests import get

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

    def process(self, directory: str):
        """
        Process the results of the NetworkPingPong experiment.

        Reads all server-*.csv files from the experiment's output directory,
        concatenates them, calculates RTT for each datagram, and prints
        various statistics (mean, std, CV, percentiles).
        Also generates and saves a histogram of RTT values.

        :param directory: The base directory where experiment results are stored.
                          This method will look into `directory/network-ping-pong/`.
        """
        full_data: Dict[str, pd.DataFrame] = {} # Type hint for clarity
        results_path = os.path.join(directory, "network-ping-pong")
        for f_path in glob.glob(os.path.join(results_path, "server-*.csv")): # server-request_id.csv
            try:
                request_id = os.path.basename(f_path).split("-", 1)[1].split(".")[0]
                # Assuming 'id' column in csv is sequence number, not request_id
                data = pd.read_csv(f_path, sep=",").drop(["id"], axis=1)
                # The original logic for concatenating data for the same request_id
                # (if multiple files existed per request_id) was `axis=1` (column-wise),
                # which is unusual. If multiple files per request_id are possible and
                # represent different sets of datagrams, row-wise (axis=0) makes more sense.
                # For simplicity, assuming one file per request_id or that files are structured
                # such that simple row-wise concatenation is intended if merging.
                # However, the current loop structure processes one file per request_id into `data`.
                # The `full_data` dict then stores one DataFrame per request_id.
                # The final `pd.concat(full_data.values())` makes sense if each DataFrame
                # in `full_data` has the same columns.
                full_data[request_id] = data
            except Exception as e:
                self.logging.error(f"Error processing file {f_path}: {e}")
                continue

        if not full_data:
            self.logging.warning(f"No data files found in {results_path} to process.")
            return

        df = pd.concat(full_data.values()).reset_index(drop=True)
        df["rtt"] = (df["server_rcv"] - df["client_send"]) + (df["client_rcv"] - df["server_send"])
        print("Network Ping Pong Results:")
        print(f"  Processed {df.shape[0]} datagrams.")
        print(f"  Mean RTT: {df['rtt'].mean():.6f} s")
        print(f"  STD RTT: {df['rtt'].std():.6f} s")
        if df['rtt'].mean() != 0: # Avoid division by zero
            print(f"  CV RTT: {df['rtt'].std() / df['rtt'].mean():.4f}")
        else:
            print("  CV RTT: N/A (mean is zero)")
        print(f"  P50 RTT: {df['rtt'].quantile(0.5):.6f} s")
        print(f"  P75 RTT: {df['rtt'].quantile(0.75):.6f} s")
        print(f"  P95 RTT: {df['rtt'].quantile(0.95):.6f} s")
        print(f"  P99 RTT: {df['rtt'].quantile(0.99):.6f} s")
        print(f"  P99.9 RTT: {df['rtt'].quantile(0.999):.6f} s")

        try:
            ax = df["rtt"].hist(bins=2000)
            # ax.set_xlim([0.01, 0.04]) # Optional: set x-axis limits if needed
            fig = ax.get_figure()
            fig.savefig(os.path.join(results_path, "rtt_histogram.png"))
            self.logging.info(f"Saved RTT histogram to {os.path.join(results_path, 'rtt_histogram.png')}")
        except Exception as e:
            self.logging.error(f"Error generating histogram: {e}")


    def receive_datagrams(self, repetitions: int, port: int, ip: str):
        """
        Receive UDP datagrams from the invoked function for network ping-pong.

        Binds a UDP socket to the specified port, asynchronously invokes the
        network benchmark function (which should send datagrams to this host/port),
        and then listens for `repetitions` number of datagrams. Records timestamps
        for received and sent datagrams and saves them to a CSV file named
        `server-{request_id}.csv` in the experiment's output directory.

        :param repetitions: The number of datagrams expected from the function.
        :param port: The local port number to bind the UDP socket to.
        :param ip: The public IP address of this host, to be passed to the function.
        """
        print(f"Starting invocation with {repetitions} repetitions on port {port}")
        socket.setdefaulttimeout(2) # Timeout for socket operations
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
        """Return the name of the experiment."""
        return "network-ping-pong"

    @staticmethod
    def typename() -> str:
        """Return the type name of this experiment class."""
        return "Experiment.NetworkPingPong"
