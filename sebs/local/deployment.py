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
    @property
    def measurement_file(self) -> Optional[str]:
        return self._measurement_file

    @measurement_file.setter
    def measurement_file(self, val: Optional[str]):
        self._measurement_file = val

    def __init__(self):
        super().__init__()
        self._functions: List[LocalFunction] = []
        self._storage: Optional[Minio]
        self._inputs: List[dict] = []
        self._memory_measurement_pids: List[int] = []
        self._measurement_file: Optional[str] = None

    def add_function(self, func: LocalFunction):
        self._functions.append(func)
        if func.memory_measurement_pid is not None:
            self._memory_measurement_pids.append(func.memory_measurement_pid)

    def add_input(self, func_input: dict):
        self._inputs.append(func_input)

    def set_storage(self, storage: Minio):
        self._storage = storage

    def serialize(self, path: str):
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

    # FIXME: do we still use it?
    @staticmethod
    def deserialize(path: str, cache_client: Cache) -> "Deployment":
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

    def shutdown(self, output_json: str):

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
