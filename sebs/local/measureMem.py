"""Memory measurement utility for Docker containers.

This script periodically reads the `memory.current` file from the container's
cgroup to record its memory usage. The measurements
are appended to a specified output file.

The measurement process:
1. Reads memory.current from the container's cgroup
2. Records the measurement with container ID and timestamp
3. Tracks precision errors when measurement intervals are exceeded
4. Continues until the container stops or process is terminated

Functions:
    measure: Main measurement function that continuously monitors container memory

Usage:
    python measureMem.py --container-id <id> --measure-interval <ms> --measurement-file <path>
"""

import subprocess
import time
import argparse


def measure(container_id: str, measure_interval: int, measurement_file: str) -> None:
    """Continuously measure memory consumption of a Docker container.

    Reads memory usage from the container's cgroup filesystem at regular intervals
    and writes measurements to the specified file. Handles different cgroup paths
    for compatibility with various Docker configurations.

    Args:
        container_id: Docker container ID to monitor
        measure_interval: Measurement interval in milliseconds
        measurement_file: Path to file for writing measurements

    Note:
        This function runs indefinitely until the process is terminated.
        It attempts two different cgroup paths to accommodate different
        Docker/systemd configurations.
    """
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


if __name__ == "__main__":
    """Parse command line arguments and start memory measurement process.

    Command line arguments:
        --container-id: Docker container ID to monitor
        --measurement-file: Path to file for writing measurements
        --measure-interval: Measurement interval in milliseconds
    """
    parser = argparse.ArgumentParser(description="Measure memory consumption of a Docker container")
    parser.add_argument(
        "--container-id", type=str, required=True, help="Docker container ID to monitor"
    )
    parser.add_argument(
        "--measurement-file", type=str, required=True, help="Path to file for writing measurements"
    )
    parser.add_argument(
        "--measure-interval", type=int, required=True, help="Measurement interval in milliseconds"
    )
    args, unknown = parser.parse_known_args()
    measure(args.container_id, args.measure_interval, args.measurement_file)
