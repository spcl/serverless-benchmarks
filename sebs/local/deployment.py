from typing import List, Optional

from sebs.local.function import LocalFunction
from sebs.local.storage import Minio
from sebs.utils import serialize


class Deployment:
    def __init__(self):
        self._functions: List[LocalFunction] = []
        self._storage: Optional[Minio]
        self._inputs: List[dict] = []

    def add_function(self, func: LocalFunction):
        self._functions.append(func)

    def add_input(self, func_input: dict):
        self._inputs.append(func_input)

    def set_storage(self, storage: Minio):
        self._storage = storage

    def serialize(self, path: str):
        with open(path, "w") as out:
            out.write(
                serialize(
                    {"functions": self._functions, "storage": self._storage, "inputs": self._inputs}
                )
            )
