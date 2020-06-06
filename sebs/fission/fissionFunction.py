from abc import ABC
from enum import Enum
from sebs.faas.function import Function
from typing import List
import subprocess


class FissionFunction(Function):
    def __init__(self, name: str):
        self._name = name

    @property
    def name(self):
        return self._name

    def sync_invoke(self, payload: dict):
        subprocess.call(["./run_fission_function.sh", self.name])

    def async_invoke(self, payload: dict):
        raise Exception("Non-trigger invoke not supported!")
