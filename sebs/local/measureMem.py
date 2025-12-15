"""
Measure memory consumption of a specified docker container.

Specifically, the pseudofile memory.current from the cgroup
pseudo-filesystem is read by a shell command (cat) every few
milliseconds while the container is running.
"""

import subprocess
import time
import argparse


def measure(container_id: str, measure_interval: int, measurement_file: str) -> None:

    f = open(measurement_file, "a")

    while True:
        time_start = time.perf_counter_ns()
        longId = "docker-" + container_id + ".scope"
        try:
            cmd = f"cat /sys/fs/cgroup/system.slice/{longId}/memory.current"
            p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, shell=True)
            f.write(f"{container_id} {int(p.communicate()[0].decode())}\n")
        except:  # noqa
            cmd = f"cat /sys/fs/cgroup/docker/{container_id}/memory.current"
            p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, shell=True)
            f.write(f"{container_id} {int(p.communicate()[0].decode())}\n")

        iter_duration = time.perf_counter_ns() - time_start
        if iter_duration / 1e6 > measure_interval and measure_interval > 0:
            f.write("precision not met\n")
        time.sleep(max(0, (measure_interval - iter_duration / 1e6) / 1000))


"""
 Parse container ID and measure interval and start memory measurement process.
"""
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--container-id", type=str)
    parser.add_argument("--measurement-file", type=str)
    parser.add_argument("--measure-interval", type=int)
    args, unknown = parser.parse_known_args()
    measure(args.container_id, args.measure_interval, args.measurement_file)
