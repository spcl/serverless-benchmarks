import base64
import datetime
import json
import logging
import os
import shutil
import time
import subprocess
import uuid
from typing import Dict, List, Optional, Tuple, Union, cast

from sebs import utils
from sebs.benchmark import Benchmark
from sebs.cache import Cache
from sebs.config import SeBSConfig
from ..faas.function import Function
from ..faas.storage import PersistentStorage
from ..faas.system import System



class fission(System):

def __init__(
        self,
        sebs_config: SeBSConfig,
        cache_client: Cache,
        docker_client: docker.client,
    ):
        super().__init__(sebs_config, cache_client, docker_client)

def initialize(self, config: Dict[str, str] = {}):
        pass

def get_storage(self, replace_existing: bool) -> PersistentStorage:
        pass

def package_code(self, benchmark: sebs.benchmark.Benchmark) -> Tuple[str, int]:
        pass

def get_function(self, code_package: sebs.benchmark.Benchmark) -> Function:
        pass

def name() -> str:
        pass