"""
Script to measure memory consumption of a specified Docker container.

This script periodically reads the `memory.current` file from the container's
cgroup in the pseudo-filesystem to record its memory usage. The measurements
are appended to a specified output file.
"""

import subprocess
import time
import argparse


def measure(container_id: str, measure_interval: int, measurement_file: str) -> None:
    """
    Periodically measure the memory usage of a Docker container and write to a file.

    The function attempts to read memory usage from two possible cgroup paths:
    1. `/sys/fs/cgroup/system.slice/docker-{container_id}.scope/memory.current`
    2. `/sys/fs/cgroup/docker/{container_id}/memory.current` (fallback)

    Memory usage is written as "{container_id} {memory_in_bytes}" per line.
    If the time taken to measure and write exceeds `measure_interval`, a
    "precision not met" message is written.

    :param container_id: The full ID of the Docker container to measure.
    :param measure_interval: The target interval in milliseconds between measurements.
                             If 0 or negative, measurements are taken as fast as possible.
    :param measurement_file: Path to the file where measurements will be appended.
    """
    # Open the measurement file in append mode.
    # Ensure this file is handled correctly regarding concurrent writes if multiple
    # instances of this script could target the same file (though typically not the case).
    with open(measurement_file, "a") as f:
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


# Ensure the file is flushed regularly if buffering is an issue for real-time monitoring.
# However, for typical usage, standard buffering should be fine.

"""
Command-line interface for the memory measurement script.

Parses arguments for container ID, measurement interval, and output file,
then starts the memory measurement process.
"""
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Measure memory consumption of a Docker container."
    )
    parser.add_argument("--container-id", type=str, required=True, help="Full ID of the Docker container.")
    parser.add_argument("--measurement-file", type=str, required=True, help="File to append measurements to.")
    parser.add_argument(
        "--measure-interval",
        type=int,
        required=True,
        help="Target interval between measurements in milliseconds.",
    )
    args = parser.parse_args() # Use parse_args, unknown args will cause error

    try:
        measure(args.container_id, args.measure_interval, args.measurement_file)
    except KeyboardInterrupt:
        print(f"Memory measurement for container {args.container_id} stopped by user.")
    except Exception as e:
        print(f"Error during memory measurement for container {args.container_id}: {e}")
        # Optionally, log to a file or re-raise depending on desired error handling.
