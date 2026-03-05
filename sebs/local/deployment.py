"""Deployment management for local execution platform.

This module provides the Deployment class for managing local function deployments,
including memory measurement collection, function lifecycle management, and
resource cleanup.

Classes:
    Deployment: Main deployment management class for local functions
"""

import json
import os
from signal import SIGKILL
from statistics import mean
from typing import List, Optional

from sebs.cache import Cache
from sebs.local.function import LocalFunction
from sebs.local.config import LocalResources
from sebs.storage.minio import Minio, MinioConfig
from sebs.utils import serialize, LoggingBase


class Deployment(LoggingBase):
    """Manages local function deployments and memory measurements.

    Attributes:
        _functions: List of deployed local functions
        _storage: Optional Minio storage instance
        _inputs: List of function input configurations
        _memory_measurement_pids: PIDs of memory measurement processes
        _measurement_file: Path to memory measurement output file
    """

    @property
    def measurement_file(self) -> Optional[str]:
        """Get the path to the memory measurement file.

        Returns:
            Optional[str]: Path to measurement file, or None if not set
        """
        return self._measurement_file

    @measurement_file.setter
    def measurement_file(self, val: Optional[str]) -> None:
        """Set the path to the memory measurement file.

        Args:
            val: Path to measurement file, or None to unset
        """
        self._measurement_file = val

    def __init__(self):
        """Initialize a new deployment."""
        super().__init__()
        self._functions: List[LocalFunction] = []
        self._storage: Optional[Minio]
        self._inputs: List[dict] = []
        self._memory_measurement_pids: List[int] = []
        self._measurement_file: Optional[str] = None

    def add_function(self, func: LocalFunction) -> None:
        """Add a function to the deployment.

        If the function has a memory measurement PID, it's also recorded.

        Args:
            func: Local function to add to the deployment
        """
        self._functions.append(func)
        if func.memory_measurement_pid is not None:
            self._memory_measurement_pids.append(func.memory_measurement_pid)

    def add_input(self, func_input: dict) -> None:
        """Add function input configuration to the deployment.

        Args:
            func_input: Dictionary containing function input configuration
        """
        self._inputs.append(func_input)

    def set_storage(self, storage: Minio) -> None:
        """Set the storage instance for the deployment.

        Args:
            storage: Minio storage instance to use
        """
        self._storage = storage

    def serialize(self, path: str) -> None:
        """Serialize deployment configuration to file.

        Includes details about functions, storage, inputs, and memory measurements.

        Args:
            path: File path to write serialized deployment configuration
        """
        with open(path, "w") as out:
            config: dict = {
                "functions": self._functions,
                "storage": self._storage,
                "inputs": self._inputs,
            }

            if self._measurement_file is not None:
                config["memory_measurements"] = {
                    "pids": self._memory_measurement_pids,
                    "file": self._measurement_file,
                }

            out.write(serialize(config))

    @staticmethod
    def deserialize(path: str, cache_client: Cache) -> "Deployment":
        """Deserialize deployment configuration from file.

        Args:
            path: File path to read serialized deployment configuration
            cache_client: Cache client for loading cached resources

        Returns:
            Deployment: Deserialized deployment instance

        Note:
            This method may be deprecated - check if still in use
        """
        with open(path, "r") as in_f:
            input_data = json.load(in_f)
            deployment = Deployment()
            for input_cfg in input_data["inputs"]:
                deployment._inputs.append(input_cfg)
            for func in input_data["functions"]:
                deployment._functions.append(LocalFunction.deserialize(func))
            if "memory_measurements" in input_data:
                deployment._memory_measurement_pids = input_data["memory_measurements"]["pids"]
                deployment._measurement_file = input_data["memory_measurements"]["file"]
            deployment._storage = Minio.deserialize(
                MinioConfig.deserialize(input_data["storage"]), cache_client, LocalResources()
            )
            return deployment

    def shutdown(self, output_json: str) -> None:
        """Shutdown the deployment and collect memory measurements.

        Terminates all memory measurement processes, processes measurement data,
        and stops all function containers. Memory measurements are aggregated
        and written to the specified output file.

        Args:
            output_json: Path to write memory measurement results
        """
        if len(self._memory_measurement_pids) > 0:

            self.logging.info("Killing memory measurement processes")

            # kill measuring processes
            for proc in self._memory_measurement_pids:
                os.kill(proc, SIGKILL)

        if self._measurement_file is not None:

            self.logging.info(f"Gathering memory measurement data in {output_json}")
            # create dictionary with the measurements
            measurements: dict = {}
            precision_errors = 0
            with open(self._measurement_file, "r") as file:
                for line in file:
                    if line == "precision not met\n":
                        precision_errors += 1

                    line_content = line.split()
                    if len(line_content) == 0:
                        continue
                    if not line_content[0] in measurements:
                        try:
                            measurements[line_content[0]] = [int(line_content[1])]
                        except ValueError:
                            continue
                    else:
                        try:
                            measurements[line_content[0]].append(int(line_content[1]))
                        except ValueError:
                            continue

            for container in measurements:
                measurements[container] = {
                    "mean mem. usage": f"{mean(measurements[container])/1e6} MB",
                    "max mem. usage": f"{max(measurements[container])/1e6} MB",
                    "number of measurements": len(measurements[container]),
                    "full profile (in bytes)": measurements[container],
                }

            # write to output_json file
            with open(output_json, "w") as out:
                if precision_errors > 0:
                    measurements["precision_errors"] = precision_errors
                json.dump(measurements, out, indent=6)

            # remove the temporary file the measurements were written to
            os.remove(self._measurement_file)

        for func in self._functions:
            func.stop()
