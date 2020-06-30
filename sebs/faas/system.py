from abc import ABC
from abc import abstractmethod
from typing import Dict, Optional, Tuple

import docker

import sebs.benchmark
from sebs.cache import Cache
from sebs.config import SeBSConfig
from .config import Config
from .function import Function
from .storage import PersistentStorage

"""
    This class provides basic abstractions for the FaaS system.
    It provides the interface for initialization of the system and storage
    services, creation and update of serverless functions and querying
    logging and measurements services to obtain error messages and performance
    measurements.
"""


class System(ABC):
    def __init__(
        self,
        system_config: SeBSConfig,
        cache_client: Cache,
        docker_client: docker.client,
    ):
        self._system_config = system_config
        self._docker_client = docker_client
        self._cache_client = cache_client

    @property
    def system_config(self) -> SeBSConfig:
        return self._system_config

    @property
    def docker_client(self) -> docker.client:
        return self._docker_client

    @property
    def cache_client(self) -> Cache:
        return self._cache_client

    @property
    @abstractmethod
    def config(self) -> Config:
        pass

    """
        Initialize the system. After the call the local or remot
        FaaS system should be ready to allocate functions, manage
        storage resources and invoke functions.

        :param config: systems-specific parameters
    """

    def initialize(self, config: Dict[str, str] = {}):
        pass

    """
        Access persistent storage instance.
        It might be a remote and truly persistent service (AWS S3, Azure Blob..),
        or a dynamically allocated local instance.

        :param replace_existing: replace benchmark input data if exists already
    """

    @abstractmethod
    def get_storage(self, replace_existing: bool) -> PersistentStorage:
        pass

    """
        Apply the system-specific code packaging routine to build benchmark.
        The benchmark creates a code directory with the following structure:
        - [benchmark sources]
        - [benchmark resources]
        - [dependence specification], e.g. requirements.txt or package.json
        - [handlers implementation for the language and deployment]

        This step allows us to change the structure above to fit different
        deployment requirements, Example: a zip file for AWS or a specific
        directory structure for Azure.

        :return: path to packaged code and its size
    """

    def package_code(
        self, directory: str, language_name: str, benchmark: str
    ) -> Tuple[str, int]:
        pass

    """
        a)  if a cached function is present and no update flag is passed,
            then just return function name
        b)  if a cached function is present and update flag is passed,
            then upload new code
        c)  if no cached function is present, then create code package and
            either create new function on AWS or update an existing one

        :param benchmark:
        :param config: JSON config for benchmark
        :param function_name: Override randomly generated function name
        :return: function name, code size
    """

    @abstractmethod
    def get_function(
        self, code_package: sebs.benchmark.Benchmark, func_name: Optional[str] = None
    ) -> Function:
        pass

    @staticmethod
    @abstractmethod
    def default_function_name(code_package: sebs.benchmark.Benchmark) -> str:
        pass

    # FIXME: trigger allocation API
    # FIXME: result query API
    # FIXME: metrics query API
    # def update_function(self, code_package):
    #    pass

    # @abstractmethod
    # def get_invocation_error(self, function_name: str,
    #   start_time: int, end_time: int):
    #    pass

    # @abstractmethod
    # def download_metrics(self):
    #    pass

    """
        Shutdown local FaaS instances, connections and clients.
    """

    @abstractmethod
    def shutdown(self) -> None:
        pass

    @staticmethod
    @abstractmethod
    def name() -> str:
        pass
