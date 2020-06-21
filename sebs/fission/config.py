from sebs.faas.config import Config, Credentials, Resources
from sebs.cache import Cache



class FissionCredentials(Credentials):
    def __init__(self):
        pass

    def initialize(config: dict, cache: Cache) -> Credentials:
        pass
     
    def serialize(self) -> dict:
        pass


class FissionResources(Resources):
    def __init__(self):
        pass

    def serialize(self) -> dict:
        pass

    def initialize(config: dict, cache: Cache) -> Resources:
        pass


class FissionConfig(Config):
    name: str
    cache: Cache
    def __init__(self, config: dict, cache: Cache):
        self.name = config['name']
        self.cache = cache
    
    @staticmethod
    def initialize(config: dict, cache: Cache) -> Config:
        return FissionConfig(config, cache)

    def credentials(self) -> Credentials:
        pass

    def resources(self) -> Resources:
        pass

    def serialize(self) -> dict:
        pass
