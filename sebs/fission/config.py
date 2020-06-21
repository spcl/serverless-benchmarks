from sebs.faas.config import Config
from sebs.cache import Cache
class FissionConfig(Config):
    def __init__(self):
        pass
    
    @staticmethod
    def initialize(config: dict, cache: Cache) -> Config:
        pass