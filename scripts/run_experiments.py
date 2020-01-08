#!/usr/bin/python3

import argparse
import collections
import copy
import docker
import json
import importlib
import minio
import os
import secrets
import subprocess
import sys
import traceback
import urllib, urllib.request
import uuid

from functools import partial

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
PACK_CODE_APP = 'pack_code.sh'
HOME_DIR = '/home/docker_user'

def iterable(val):
    return val if isinstance(val, collections.Iterable) else [val, ]

def run_container(client, volumes, code_package):
    return client.containers.run(
            'sebs-local-python',
            command='/bin/bash',
            volumes = {
                **volumes,
                code_package : {'bind': os.path.join(HOME_DIR, 'code.zip'), 'mode': 'ro'}
            },
            # required to access perf counters
            # alternative: use custom seccomp profile
            privileged=True,
            user='1000:1000',
            network_mode="host",
            remove=True,
            stdout=True, stderr=True,
            detach=True, tty=True
        )

def run_experiment_time(output_dir, volumes, input_config):
    names = []
    for option in ['warm', 'cold']:
        name = 'time_{}'.format(option)
        file_name = '{}.json'.format(name)
        with open(file_name, 'w') as f:
            experiment = {
                'language': 'python',
                'name': name,
                'type': 'time',
                'experiment_options': option
            }
            volumes[os.path.join(output_dir, file_name)] = {
                    'bind': os.path.join(HOME_DIR, file_name), 'mode': 'ro'
                }
            cfg_copy = copy.deepcopy(input_config)
            cfg_copy['benchmark'].update(experiment)
            json.dump(cfg_copy, f, indent=2)
        names.append(name)
    return [[x, 1, lambda *args, **kwargs: None, False, lambda x: None] for x in names]

def run_experiment_papi_ipc(output_dir, volumes, input_config):
    name = 'ipc_papi'
    file_name = '{}.json'.format(name)
    with open(file_name, 'w') as f:
        experiment = {
            'language': 'python',
            'name': 'ipc_papi',
            'type': 'papi',
            'papi': {
                'events': ['PAPI_TOT_CYC', 'PAPI_TOT_INS', 'PAPI_LST_INS'],
                'overflow_instruction_granularity' : 1e6,
                'overflow_buffer_size': 1e5
            }
        }
        volumes[os.path.join(output_dir, file_name)] = {
                'bind': os.path.join(HOME_DIR, file_name), 'mode': 'ro'
            }
        cfg_copy = copy.deepcopy(input_config)
        cfg_copy['benchmark'].update(experiment)
        json.dump(cfg_copy, f, indent=2)
    return [[name, 1, lambda *args, **kwargs: None, False, lambda x: None]]


def proc_clean(proc, port):
    subprocess.run(['curl', '-X', 'POST', 'localhost:{}/dump'.format(port)])
    proc.kill()
    print('Proc analyzer output', file=output_file)
    print(proc.stdout.read().decode('utf-8'), file=output_file)

def wait(port, count):
    values = 0
    while values != count:
        response = urllib.request.urlopen('http://localhost:{}/processed_apps'.format(port), {})
        data = response.read()
        values = json.loads(data)['apps']
    
def run_experiment_mem(output_dir, volumes, input_config):
    name = ['mem_single', 'mem_multiple']
    #TODO: port detection
    base_port = [8081, 8082]
    apps = [1, 10]
    detach = [False, True]
    verifier = [lambda x: None, partial(wait, base_port[1])]
    experiments = []
    for i in range(0, len(apps)):
        v = apps[i]
        file_name = '{}.json'.format(name[i])
        proc = subprocess.Popen(
                [os.path.join(SCRIPT_DIR, 'proc_analyzer.py'), str(base_port[i]),
                    os.path.join(name[i], 'results', '{}.csv'.format(name[i])), 'memory', str(v)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT
            )
        if proc.returncode is not None:
            print('Memory analyzer finished unexpectedly', file=output_file)
            print(proc.stderr.decode('utf-8'), output_file)
        with open(file_name, 'w') as f:
            experiment = {
                'language': 'python',
                'name': name[i],
                'type': 'mem',
                'repetitions': 1,
                'disable_gc': False,
                'analyzer': {
                    'participants' : v,
                    'analyzer_ip': 'localhost:{}'.format(base_port[i]),
                }
            }
            volumes[os.path.join(output_dir, file_name)] = {
                    'bind': os.path.join(HOME_DIR, file_name), 'mode': 'ro'
                }
            cfg_copy = copy.deepcopy(input_config)
            cfg_copy['benchmark'].update(experiment)
            json.dump(cfg_copy, f, indent=2)
        experiments.append( [name[i], v, partial(proc_clean, proc, base_port[i]), detach[i], verifier[i]] )
    return experiments

def run_experiment_disk_io(output_dir, volumes, input_config):
    name = 'disk-io'
    base_port = 8081
    apps = 1
    detach = False
    verifier = lambda x: None
    experiments = []
    file_name = '{}.json'.format(name)
    proc = subprocess.Popen(
            [os.path.join(SCRIPT_DIR, 'proc_analyzer.py'), str(base_port),
                os.path.join(name, 'results', '{}.csv'.format(name)), 'disk_io', str(apps)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT
        )
    if proc.returncode is not None:
        print('Analyzer finished unexpectedly', file=output_file)
        print(proc.stderr.decode('utf-8'), output_file)
    with open(file_name, 'w') as f:
        experiment = {
            'language': 'python',
            'name': name,
            'type': 'disk-io',
            'repetitions': 1,
            'disable_gc': False,
            'analyzer': {
                'participants' : apps,
                'analyzer_ip': 'localhost:{}'.format(base_port),
            }
        }
        volumes[os.path.join(output_dir, file_name)] = {
                'bind': os.path.join(HOME_DIR, file_name), 'mode': 'ro'
            }
        cfg_copy = copy.deepcopy(input_config)
        cfg_copy['benchmark'].update(experiment)
        json.dump(cfg_copy, f, indent=2)
    return [[name, apps, partial(proc_clean, proc, base_port), detach, verifier]]

experiments = {
        'time' : run_experiment_time,
        'papi' : run_experiment_papi_ipc,
        'memory' : run_experiment_mem,
        'disk_io' : run_experiment_disk_io
        }
experiments['all'] = experiments.values()
output_file = None
client = docker.from_env()
verbose = False

parser = argparse.ArgumentParser(description='Run local app experiments.')
parser.add_argument('benchmark', type=str, help='Benchmark name')
parser.add_argument('output_dir', type=str, help='Output dir')
parser.add_argument('language', choices=['python', 'nodejs', 'cpp'],
                    help='Benchmark language')
parser.add_argument('experiment', choices=['time', 'papi', 'memory', 'disk_io', 'all'],
                    help='Benchmark language')
parser.add_argument('size', choices=['test', 'small', 'large'],
                    help='Benchmark input test size')
parser.add_argument('--repetitions', action='store', default=5, type=int,
                    help='Number of experimental repetitions')
parser.add_argument('--verbose', action='store', default=False, type=bool,
                    help='Verbose output')

def find(name, path):
    for root, dirs, files in os.walk(path):
        if name in dirs:
            return os.path.join(root, name)
    return None

def create_output(dir):
    output_dir = os.path.abspath(dir)
    if not os.path.exists(output_dir):
        os.mkdir(output_dir)
    os.chdir(output_dir)
    return output_dir, open('out.log', 'w')

def find_benchmark(benchmark):
    benchmarks_dir = os.path.join(SCRIPT_DIR, '..', 'benchmarks')
    benchmark_path = find(benchmark, benchmarks_dir)
    if benchmark_path is None:
        print('Could not find benchmark {} in {}'.format(args.benchmark, benchmarks_dir))
        sys.exit(1)
    return benchmark_path

def create_code_package(benchmark, benchmark_path, language):
    output = os.popen('{} -b {} -l {} {}'.format(
            os.path.join(SCRIPT_DIR, PACK_CODE_APP),
            benchmark_path, language,
            '-v' if verbose else ''
        )).read()
    print(output, file=output_file)
    code_package = '{}.zip'.format(benchmark)
    # measure uncompressed code size with unzip -l
    ret = subprocess.run(['unzip -l {} | awk \'END{{print $1}}\''.format(code_package)], shell=True, stdout = subprocess.PIPE)
    if ret.returncode != 0:
        raise RuntimeError('Code size measurement failed: {}'.format(ret.stdout.decode('utf-8')))
    code_size = int(ret.stdout.decode('utf-8'))
    return code_package, code_size

class minio_storage:
    storage_container = None
    input_buckets = []
    output_buckets = []
    access_key = None
    secret_key = None
    port = 9000
    location = 'us-east-1'
    connection = None

    def __init__(self, benchmark, size, buckets):
        if buckets[0] + buckets[1] > 0:
            self.start()
            self.connection = self.get_connection()
            for i in range(0, buckets[0]):
                self.input_buckets.append(
                        self.create_bucket('{}-{}-input'.format(benchmark, size)))
            for i in range(0, buckets[1]):
                self.output_buckets.append(
                        self.create_bucket('{}-{}-output'.format(benchmark, size)))
             
    def start(self):
        self.access_key = secrets.token_urlsafe(32)
        self.secret_key = secrets.token_hex(32)
        print('Starting minio instance at localhost:{}'.format(self.port))
        print('ACCESS_KEY', self.access_key)
        print('SECRET_KEY', self.secret_key)
        self.storage_container = client.containers.run(
            'minio/minio',
            command='server /data',
            ports={str(self.port): self.port},
            environment={
                'MINIO_ACCESS_KEY' : self.access_key,
                'MINIO_SECRET_KEY' : self.secret_key
            },
            remove=True,
            stdout=True, stderr=True,
            detach=True
        )

    def stop(self):
        print('Stopping minio instance at localhost:{}'.format(self.port))
        self.storage_container.stop()

    def get_connection(self):
        return minio.Minio('localhost:{}'.format(self.port),
                access_key=self.access_key,
                secret_key=self.secret_key,
                secure=False)

    def config_to_json(self):
        if self.storage_container is not None:
            return {
                    'address': 'localhost:{}'.format(self.port),
                    'secret_key': self.secret_key,
                    'access_key': self.access_key,
                    'input': self.input_buckets,
                    'output': self.output_buckets
                }
        else:
            return {}

    def create_bucket(self, name):
        # minio has limit of bucket name to 16 characters
        bucket_name = '{}-{}'.format(name, str(uuid.uuid4())[0:16])
        try:
            self.connection.make_bucket(bucket_name, location=self.location)
            print('Created bucket {}'.format(bucket_name))
            return bucket_name
        except (minio.error.BucketAlreadyOwnedByYou, minio.error.BucketAlreadyExists, minio.error.ResponseError) as err:
            print('Bucket creation failed!')
            print(err)
            # rethrow
            raise err

    def uploader_func(self, bucket, file, filepath):
        try:
            self.connection.fput_object(bucket, file, filepath)
        except minio.error.ResponseError as err:
            print('Upload failed!')
            print(err)
            raise(err)

class minio_uploader:
    pass

def prepare_input(benchmark, benchmark_path, size):
    # Look for input generator file in the directory containing benchmark
    sys.path.append(benchmark_path)
    mod = importlib.import_module('input')
    buckets = mod.buckets_count()
    storage = minio_storage(benchmark, size, buckets)
    # Get JSON and upload data as required by benchmark
    input_config = mod.generate_input(size, storage.input_buckets, storage.output_buckets, storage.uploader_func)
    return input_config, storage

try:

    # 0. Input args
    args = parser.parse_args()
    verbose = args.verbose

    # 1. Create output dir
    output_dir, output_file = create_output(args.output_dir)

    # 2. Locate benchmark
    benchmark_path = find_benchmark(args.benchmark)

    # 3. Build code package
    code_package, code_size = create_code_package(args.benchmark, benchmark_path, args.language)

    # 4. Prepare environment
    # TurboBoost, disable HT, power cap, decide on which cores to use

    # 5. Prepare benchmark input
    input_config, storage = prepare_input(args.benchmark, benchmark_path, args.size)

    # 6. Create experiment config
    app_config = {'name' : args.benchmark, 'size' : code_size}
    benchmark_config = {}
    benchmark_config['repetitions'] = args.repetitions
    benchmark_config['disable_gc'] = True
    storage_config = storage.config_to_json()
    if storage_config:
        benchmark_config['storage'] = storage_config
    input_config = { 'input' : input_config, 'app': app_config, 'benchmark' : benchmark_config }

    # 7. Select experiments
    volumes = {}
    enabled_experiments = []
    for ex_func in iterable(experiments[args.experiment]):
        enabled_experiments.extend( ex_func(output_dir, volumes, input_config) )

    # 8. Start measurement processes
    for experiment, count, cleanup, detach, wait_f in enabled_experiments:

        containers = [None] * count
        for i in range(0, count):
            # 7. Start docker instance with code and input
            containers[i] = run_container(client, volumes, os.path.join(output_dir, code_package))
       
            # 8. Run experiments
            exit_code, out = containers[i].exec_run('/bin/bash run.sh {}.json'.format(experiment), detach=detach)
            if not detach:
                print('Experiment: {} exit code: {}'.format(experiment, exit_code), file=output_file)
                if exit_code == 0:
                    print('Output: ', out.decode('utf-8'), file=output_file)
                else:
                    print('Experiment {} failed! Exit code {}'.format(experiment, exit_code))
                    print(exit_code)
            else:
                wait_f(i+1)

        # 9. Copy result data
        os.makedirs(experiment, exist_ok=True)
        for container in containers:
            os.popen('docker cp {}:{} {}'.format(container.id, os.path.join(HOME_DIR, 'results'), experiment))
            os.popen('docker cp {}:{} {}'.format(container.id, os.path.join(HOME_DIR, 'logs'), experiment))
            # 10. Kill docker instance
            container.stop()

        # 11. Cleanup active measurement processes
        cleanup()

    # Stop measurement processes

    # Clean data storage
    #storage.stop()
except Exception as e:
    print(e)
    traceback.print_exc()
    print('Experiments failed!')
