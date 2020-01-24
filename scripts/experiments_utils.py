import docker
import glob
import logging
import importlib
import json
import os
import shutil
import sys
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
PROJECT_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir)
PACK_CODE_APP = 'pack_code_{}.sh'

def project_absolute_path(*paths: str):
    return os.path.join(PROJECT_DIR, *paths)

# Executing with shell provides options such as wildcard expansion
def execute(cmd, shell=False):
    if not shell:
        cmd = cmd.split()
    ret = subprocess.run(cmd, shell=shell, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if ret.returncode:
        raise RuntimeError('Running {} failed!\n Output: {}'.format(cmd, ret.stdout.decode('utf-8')))
    return ret.stdout.decode('utf-8')

def find(name, path):
    for root, dirs, files in os.walk(path):
        if name in dirs:
            return os.path.join(root, name)
    return None

def create_output(dir, preserve_dir, verbose):
    output_dir = os.path.abspath(dir)
    if os.path.exists(output_dir) and not preserve_dir:
        shutil.rmtree(output_dir)
    if not os.path.exists(output_dir):
        os.mkdir(output_dir)
    os.chdir(output_dir)
    logging.basicConfig(
        filename=os.path.join(output_dir, 'out.log'),
        filemode='w',
        format='%(asctime)s,%(msecs)d %(levelname)s %(message)s',
        datefmt='%H:%M:%S',
        level=logging.DEBUG if verbose else logging.INFO
    )
    return output_dir

'''
    Locate directory corresponding to a benchmark in benchmarks
    or benchmarks-data directory.

    :param benchmark: Benchmark name.
    :param path: Path for lookup, relative to repository.
    :return: relative path to directory corresponding to benchmark
'''
def find_benchmark(benchmark: str, path: str):
    benchmarks_dir = os.path.join(PROJECT_DIR, path)
    benchmark_path = find(benchmark, benchmarks_dir)
    return benchmark_path

'''
    Locates benchmark input generator, inspect how many storage buckets
    are needed and launches corresponding storage instance, if necessary.

    :param client: Deployment client
    :param benchmark:
    :param benchmark_path:
    :param size: Benchmark workload size
    :param update_storage: if true then files in input buckets are reuploaded
'''
def prepare_input(client :object, benchmark :str, benchmark_path :str,
        size :str, update_storage :bool):
    benchmark_data_path = find_benchmark(benchmark, 'benchmarks-data')
    # Look for input generator file in the directory containing benchmark
    sys.path.append(benchmark_path)
    mod = importlib.import_module('input')
    buckets = mod.buckets_count()
    storage = client.get_storage(benchmark, buckets, update_storage)
    # Get JSON and upload data as required by benchmark
    input_config = mod.generate_input(benchmark_data_path,
            size, storage.input(),
            storage.output(), storage.uploader_func)
    return input_config


'''
    Download all files in a storage bucket.
    Warning: assumes flat directory in a bucket! Does not handle bucket files
    with directory marks in a name, e.g. 'dir1/dir2/file'
'''
def download_bucket(storage_client :object, bucket_name :str, output_dir :str):

    files = storage_client.list_bucket(bucket_name)
    for f in files:
        output_file = os.path.join(output_dir, f)
        if not os.path.exists(output_file):
            storage_client.download(bucket_name, f, output_file)

