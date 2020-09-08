from sebs.cache import Cache
from sebs.faas.config import Credentials, Resources, Config


class OpenWhiskCredentials(Credentials):
    def __init__(self):
        pass

    @staticmethod
    def initialize(config: dict, cache: Cache) -> Credentials:
        return OpenWhiskCredentials()

    def serialize(self) -> dict:
        pass


class OpenWhiskResources(Resources):

    @staticmethod
    def initialize(config: dict, cache: Cache) -> Resources:
        return OpenWhiskResources()

    def serialize(self) -> dict:
        return {"": ""}


class OpenWhiskConfig(Config):
    name: str
    shutdownStorage: bool
    cache: Cache

    def __init__(self, config: dict, cache: Cache):
        self.name = config['name']
        self.shutdownStorage = config['shutdownStorage']
        self.removeCluster = config['removeCluster']
        self.cache = cache

    @property
    def credentials(self) -> Credentials:
        pass

    @property
    def resources(self) -> Resources:
        pass

    @staticmethod
    def initialize(config: dict, cache: Cache) -> Config:
        return OpenWhiskConfig(config, cache)

    def serialize(self) -> dict:
        pass
