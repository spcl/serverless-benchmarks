import json
import logging
import os
import shutil
import subprocess
import sys

from sebs.faas.storage import PersistentStorage


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


def serialize(obj) -> str:
    if hasattr(obj, "serialize"):
        return json.dumps(obj.serialize(), sort_keys=True, indent=2)
    else:
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
    logging_format = "%(asctime)s,%(msecs)d %(levelname)s %(message)s"
    logging_date_format = "%H:%M:%S"

    # default file log
    logging.basicConfig(
        filename=os.path.join(output_dir, "out.log"),
        filemode="w",
        format=logging_format,
        datefmt=logging_date_format,
        level=logging.DEBUG if verbose else logging.INFO,
    )
    # Add stdout output
    stdout = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(logging_format, logging_date_format)
    stdout.setFormatter(formatter)
    stdout.setLevel(logging.DEBUG if verbose else logging.INFO)
    logging.getLogger().addHandler(stdout)

    # disable information from libraries logging to decrease output noise
    for name in logging.root.manager.loggerDict:
        if name.startswith("urllib3"):
            logging.getLogger(name).setLevel(logging.ERROR)

    return output_dir


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


"""
    Download all files in a storage bucket.
    Warning: assumes flat directory in a bucket! Does not handle bucket files
    with directory marks in a name, e.g. 'dir1/dir2/file'
"""


def download_bucket(
    storage_client: PersistentStorage, bucket_name: str, output_dir: str
):

    files = storage_client.list_bucket(bucket_name)
    for f in files:
        output_file = os.path.join(output_dir, f)
        if not os.path.exists(output_file):
            storage_client.download(bucket_name, f, output_file)
