from enum import Enum


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

    _update_code: bool
    _update_storage: bool
    _download_results: bool
    _runtime: Runtime

    @property
    def update_code(self) -> bool:
        return self._update_code

    @property
    def update_storage(self) -> bool:
        return self._update_storage

    @property
    def runtime(self) -> Runtime:
        return self._runtime

    def serialize(self) -> dict:
        out = {
            "update_code": self._update_code,
            "update_storage": self._update_storage,
            "download_results": self._download_results,
            "runtime": self._runtime.serialize(),
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
        return cfg
