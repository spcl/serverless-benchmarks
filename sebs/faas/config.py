from abc import ABC
from abc import abstractmethod


from sebs import cache

# FIXME: Replace type hints for static generators after migration to 3.7
# https://stackoverflow.com/questions/33533148/how-do-i-specify-that-the-return-type-of-a-method-is-the-same-as-the-class-itsel


class Credentials(ABC):

    """
        The order of credentials initialization:
        1. Load credentials from cache.
        2. If any new vaues are provided in the config, they override cache values.
        3. If nothing is provided, initialize cache using environmental variables.
        4. If no information is provided, then failure is reported.
    """

    @staticmethod
    @abstractmethod
    def initialize(config: dict, cache: cache.Cache) -> "Credentials":
        pass


class Resources(ABC):
    pass


class Config(ABC):

    _region: str

    @property
    def region(self) -> str:
        return self._region

    @property
    @abstractmethod
    def credentials(self) -> Credentials:
        pass

    @property
    @abstractmethod
    def resources(self) -> Resources:
        pass

    @staticmethod
    @abstractmethod
    def initialize(config: dict, cache: cache.Cache) -> "Config":
        pass
