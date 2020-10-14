from enum import Enum
from typing import Dict


class Language(Enum):
    PYTHON = "python"
    NODEJS = "nodejs"

    # FIXME: 3.7+ python with future annotations
    @staticmethod
    def deserialize(val: str) -> "Language":
        for member in Language:
            if member.value == val:
                return member
        raise Exception("Unknown language type {}".format(member))


class Runtime:

    _language: Language
    _version: str

    @property
    def language(self) -> Language:
        return self._language

    @property
    def version(self) -> str:
        return self._version

    @version.setter
    def version(self, val: str):
        self._version = val

    def serialize(self) -> dict:
        return {"language": self._language.value, "version": self._version}

    # FIXME: 3.7+ python with future annotations
    @staticmethod
    def deserialize(config: dict) -> "Runtime":
        cfg = Runtime()
        languages = {"python": Language.PYTHON, "nodejs": Language.NODEJS}
        cfg._language = languages[config["language"]]
        cfg._version = config["version"]
        return cfg


class Config:
    def __init__(self):
        self._update_code: bool = False
        self._update_storage: bool = False
        self._download_results: bool = False
        self._flags: Dict[str, bool] = {}
        self._experiment_configs: Dict[str, dict] = {}
        self._runtime = Runtime()

    @property
    def update_code(self) -> bool:
        return self._update_code

    @update_code.setter
    def update_code(self, val: bool):
        self._update_code = val

    @property
    def update_storage(self) -> bool:
        return self._update_storage

    def check_flag(self, key: str) -> bool:
        return False if key not in self._flags else self._flags[key]

    @property
    def runtime(self) -> Runtime:
        return self._runtime

    def experiment_settings(self, name: str) -> dict:
        return self._experiment_configs[name]

    def serialize(self) -> dict:
        out = {
            "update_code": self._update_code,
            "update_storage": self._update_storage,
            "download_results": self._download_results,
            "runtime": self._runtime.serialize(),
            "flags": self._flags,
            "experiments": self._experiment_configs,
        }
        return out

    # FIXME: 3.7+ python with future annotations
    @staticmethod
    def deserialize(config: dict) -> "Config":

        cfg = Config()
        cfg._update_code = config["update_code"]
        cfg._update_storage = config["update_storage"]
        cfg._download_results = config["download_results"]
        cfg._runtime = Runtime.deserialize(config["runtime"])
        cfg._flags = config["flags"] if "flags" in config else {}

        from sebs.experiments import (
            NetworkPingPong,
            PerfCost,
            InvocationOverhead,
            ServiceAccessLatency
        )

        for exp in [NetworkPingPong, PerfCost, InvocationOverhead, ServiceAccessLatency]:
            if exp.name() in config:
                cfg._experiment_configs[exp.name()] = config[exp.name()]

        return cfg
