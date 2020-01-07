#!/usr/bin/python3

import argparse
import collections
import copy
import docker
import json
import importlib
import os
import sys
import subprocess
import urllib, urllib.request

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

def run_experiment_time(volumes, input_config):
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

def run_experiment_papi_ipc(volumes, input_config):
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
    
def run_experiment_mem(volumes, input_config):
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

def run_experiment_disk_io(volumes, input_config):
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
args = parser.parse_args()

def find(name, path):
    for root, dirs, files in os.walk(path):
        if name in dirs:
            return os.path.join(root, name)
    return None

# 1. Create output dir
output_dir = os.path.abspath(args.output_dir)
if not os.path.exists(output_dir):
    os.mkdir(output_dir)
os.chdir(output_dir)
output_file = open('out.log', 'w')

# 2. Locate benchmark
benchmarks_dir = os.path.join(SCRIPT_DIR, '..', 'benchmarks')
benchmark_path = find(args.benchmark, benchmarks_dir)
if benchmark_path is None:
    print('Could not find benchmark {} in {}'.format(args.benchmark, benchmarks_dir))
    sys.exit(1)

# 3. Build code package

output = os.popen('{} -b {} -l {}'.format(
        os.path.join(SCRIPT_DIR, PACK_CODE_APP),
        benchmark_path, args.language
    )).read()
print(output, file=output_file)
code_package = '{}.zip'.format(args.benchmark)
# measure uncompressed code size with unzip -l
ret = subprocess.run(['unzip -l {} | awk \'END{{print $1}}\''.format(code_package)], shell=True, stdout = subprocess.PIPE)
code_size = int(ret.stdout.decode('utf-8'))


# 4. Prepare environment

# TurboBoost, disable HT, power cap, decide on which cores to use

# 5. Prepare benchmark input

# Look for input generator file in the directory containing benchmark
sys.path.append(benchmark_path)
mod = importlib.import_module('python.input')
buckets = mod.buckets_count()
storage_container = None
input_buckets = output_buckets = []
uploader_func = None
if buckets[0] + buckets[1] > 0:
    # Run local database
    storage_container = start_storage()
# Get JSON and upload data as required by benchmark
input_config = mod.generate_input(args.size, input_buckets, output_buckets, uploader_func)

# 6. Create input for each experiment

# TODO: generate input
app_config = {'name' : args.benchmark, 'size' : code_size}
benchmark_config = {}
benchmark_config['repetitions'] = args.repetitions
benchmark_config['disable_gc'] = True
input_config = { 'input' : input_config, 'app': app_config, 'benchmark' : benchmark_config }

client = docker.from_env()
volumes = {}
enabled_experiments = []
for ex_func in iterable(experiments[args.experiment]):
    enabled_experiments.extend( ex_func(volumes, input_config) )

# Start measurement processes
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

