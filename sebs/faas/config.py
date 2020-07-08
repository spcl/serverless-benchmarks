from abc import ABC
from abc import abstractmethod

from sebs.cache import Cache
from sebs.utils import LoggingHandler

# FIXME: Replace type hints for static generators after migration to 3.7
# https://stackoverflow.com/questions/33533148/how-do-i-specify-that-the-return-type-of-a-method-is-the-same-as-the-class-itsel

"""
    Credentials for FaaS system used to authorize operations on functions
    and other resources.

    The order of credentials initialization:
    1. Load credentials from cache.
    2. If any new vaues are provided in the config, they override cache values.
    3. If nothing is provided, initialize using environmental variables.
    4. If no information is provided, then failure is reported.
"""


class Credentials(ABC, LoggingHandler):
    def __init__(self):
        super().__init__()

    """
        Create credentials instance from user config and cached values.
    """

    @staticmethod
    @abstractmethod
    def initialize(config: dict, cache: Cache) -> "Credentials":
        pass

    """
        Serialize to JSON for storage in cache.
    """

    @abstractmethod
    def serialize(self) -> dict:
        pass


"""
    Class grouping resources allocated at the FaaS system to execute functions
    and deploy various services. Examples might include IAM roles and API gateways
    for HTTP triggers.

    Storage resources are handled seperately.
"""


class Resources(ABC, LoggingHandler):
    def __init__(self):
        super().__init__()

    """
        Create credentials instance from user config and cached values.
    """

    @staticmethod
    @abstractmethod
    def initialize(config: dict, cache: Cache) -> "Resources":
        pass

    """
        Serialize to JSON for storage in cache.
    """

    @abstractmethod
    def serialize(self) -> dict:
        pass


"""
    FaaS system config defining cloud region (if necessary), credentials and
    resources allocated.
"""


class Config(ABC, LoggingHandler):

    _region: str

    def __init__(self):
        super().__init__()

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
    def initialize(config: dict, cache: Cache) -> "Config":
        pass

    @abstractmethod
    def serialize(self) -> dict:
        pass
