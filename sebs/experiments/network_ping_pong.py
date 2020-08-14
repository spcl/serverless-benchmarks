import os
import shutil
from datetime import datetime
from itertools import repeat
from multiprocessing.dummy import Pool as ThreadPool

from sebs.faas.system import System as FaaSSystem
from sebs.experiments.experiment import Experiment
from sebs.experiments.config import Config as ExperimentConfig


class NetworkPingPong(Experiment):

    def __init__(self, config: ExperimentConfig):
        super().__init__(config)

    def prepare(self, sebs_client: "SeBS", deployment_client: FaaSSystem):

        # deploy network test function
        from sebs import Benchmark
        from sebs import SeBS
        benchmark = sebs_client.get_benchmark(
            "020.network-benchmark",
            deployment_client,
            self.config
        )
        self._function = deployment_client.get_function(benchmark)
        self._storage = deployment_client.get_storage(
            replace_existing=True
        )
        self.benchmark_input = benchmark.prepare_input(storage=self._storage, size="test")
        self._out_dir = os.path.join(sebs_client.output_dir, 'network-ping-pong')
        if os.path.exists(self._out_dir):
            shutil.rmtree(self._out_dir)
        os.mkdir(self._out_dir)

    def run(self):
       
        from requests import get
        ip = get('http://checkip.amazonaws.com/').text.rstrip()
        settings = self.config.experiment_settings(self.name())
        invocations = settings['invocations']
        repetitions = settings['repetitions']
        threads = settings['threads']

        pool = ThreadPool(threads)
        ports = range(12000, 12000 + invocations)
        ret = pool.starmap(self.receive_datagrams,
            zip(repeat(repetitions, invocations), ports, repeat(ip, invocations))
        )
        #requests = []
        #for val in ret:
        #    print(val)
        import time
        time.sleep(5)
        self._storage.download_bucket(self.benchmark_input['output-bucket'], self._out_dir)

    def receive_datagrams(self, repetitions: int, port: int, ip: str):

        import csv, socket
        print(f"Starting invocation with {repetitions} repetitions on port {port}")
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server_socket.bind(('', port))

        input_benchmark = {
            "server-address": ip,
            "server-port": port,
            "repetitions": repetitions,
            **self.benchmark_input
        }
        self._function.triggers[0].async_invoke(input_benchmark)
        
        times = []
        i = 0
        j = 0
        update_counter = int(repetitions / 10)
        while i < repetitions + 1:
            message, address = server_socket.recvfrom(1024)
            timestamp_rcv = datetime.now().timestamp()
            timestamp_send = datetime.now().timestamp()
            server_socket.sendto(message, address)
            if i > 0:
                times.append([i, timestamp_rcv, timestamp_send])
            if j == update_counter:
                print(f"Invocation on port {port} processed {i} requests.")
                j = 0
            i += 1
            j += 1
        request_id = message.decode()

        output_file = os.path.join(self._out_dir, f"server-{request_id}.csv")
        with open(output_file, 'w') as csvfile:
            writer = csv.writer(csvfile, delimiter=',')
            writer.writerow(["id", "server_rcv", "server_send"])
            for row in times:
                writer.writerow(row)

    @staticmethod
    def name() -> str:
        return "network-ping-pong"

    @staticmethod
    def typename() -> str:
        return "Experiment.PerfCost"
