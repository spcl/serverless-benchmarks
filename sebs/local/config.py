from sebs.cache import Cache
from sebs.faas.config import Config, Credentials, Resources
from sebs.utils import LoggingHandlers


class LocalCredentials(Credentials):
    def serialize(self) -> dict:
        return {}

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Credentials:
        return LocalCredentials()


class LocalResources(Resources):
    def serialize(self) -> dict:
        return {}

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Resources:
        return LocalResources()


class LocalConfig(Config):
    def __init__(self):
        super().__init__()
        self._credentials = LocalCredentials()
        self._resources = LocalResources()

    @staticmethod
    def typename() -> str:
        return "Local.Config"

    @staticmethod
    def initialize(cfg: Config, dct: dict):
        pass

    @property
    def credentials(self) -> LocalCredentials:
        return self._credentials

    @property
    def resources(self) -> LocalResources:
        return self._resources

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Config:

        config_obj = LocalConfig()
        config_obj.logging_handlers = handlers
        return config_obj

    def serialize(self) -> dict:
        return {}
