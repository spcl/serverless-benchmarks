import json
import logging
import os
import shutil
import subprocess
import sys
from typing import Any, Type, TypeVar, Optional

PROJECT_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir)
PACK_CODE_APP = "pack_code_{}.sh"


def project_absolute_path(*paths: str):
    return os.path.join(PROJECT_DIR, *paths)


class JSONSerializer(json.JSONEncoder):
    def default(self, o):
        if hasattr(o, "serialize"):
            return o.serialize()
        elif isinstance(o, dict):
            return str(o)
        else:
            return vars(o)


def serialize(obj):
    return json.dumps(obj, cls=JSONSerializer, sort_keys=True, indent=2)


# Executing with shell provides options such as wildcard expansion
def execute(cmd, shell=False, cwd=None):
    if not shell:
        cmd = cmd.split()
    ret = subprocess.run(
        cmd, shell=shell, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    if ret.returncode:
        raise RuntimeError(
            "Running {} failed!\n Output: {}".format(cmd, ret.stdout.decode("utf-8"))
        )
    return ret.stdout.decode("utf-8")


def find(name, path):
    for root, dirs, files in os.walk(path):
        if name in dirs:
            return os.path.join(root, name)
    return None


def create_output(directory, preserve_dir, verbose):
    output_dir = os.path.abspath(directory)
    if os.path.exists(output_dir) and not preserve_dir:
        shutil.rmtree(output_dir)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
    os.chdir(output_dir)

    configure_logging(output_dir, verbose)

    return output_dir

def configure_logging(verbose: bool = False, output_dir: Optional[str] = None):
    logging_format = "%(asctime)s,%(msecs)d %(levelname)s %(name)s: %(message)s"
    logging_date_format = "%H:%M:%S"

    # default file log
    options = {
        "format": logging_format,
        "datefmt": logging_date_format,
        "level": logging.DEBUG if verbose else logging.INFO
    }
    if output_dir:
        options = {
            **options,
            "filename": os.path.join(output_dir, "out.log"),
            "filemode": "w"
        }
    logging.basicConfig(**options)
    # Add stdout output
    if output_dir:
        stdout = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(logging_format, logging_date_format)
        stdout.setFormatter(formatter)
        stdout.setLevel(logging.DEBUG if verbose else logging.INFO)
        logging.getLogger().addHandler(stdout)
    # disable information from libraries logging to decrease output noise
    for name in logging.root.manager.loggerDict:
        if name.startswith("urllib3") or name.startswith("docker") or name.startswith("botocore"):
            logging.getLogger(name).setLevel(logging.ERROR)


"""
    Locate directory corresponding to a benchmark in benchmarks
    or benchmarks-data directory.

    :param benchmark: Benchmark name.
    :param path: Path for lookup, relative to repository.
    :return: relative path to directory corresponding to benchmark
"""


def find_benchmark(benchmark: str, path: str):
    benchmarks_dir = os.path.join(PROJECT_DIR, path)
    benchmark_path = find(benchmark, benchmarks_dir)
    return benchmark_path


class LoggingHandler:
    def __init__(self):
        if hasattr(self, "typename"):
            self.logging = logging.getLogger(self.typename())
        else:
            self.logging = logging.getLogger(self.__class__.__name__)


C = TypeVar("C", bound=Type[Any])


def namedlogging(name=None):
    def decorated_cls(cls: C) -> C:
        @classmethod  # type: ignore
        def _logging(cls, msg: str):
            if name:
                logging.info(f"{name}: {msg}")
            else:
                logging.info(f"{cls.__name__}: {msg}")

        setattr(cls, "logging", _logging)
        return cls

    return decorated_cls
