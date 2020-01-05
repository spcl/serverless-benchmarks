#!/usr/bin/python3

import argparse
import copy
import docker
import json
import os
import sys
import subprocess

from functools import partial

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
PACK_CODE_APP = 'pack_code.sh'
HOME_DIR = '/home/docker_user'

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
    return [[x, lambda *args, **kwargs: None] for x in names]

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
    return [[name, lambda *args, **kwargs: None]]

def user_group_ids():
    pass
    #subprocess.run

def mem_clean(proc, port):
    #pass
    subprocess.run(['curl', '-X', 'POST', 'localhost:{}/dump'.format(port)])
    #proc.kill()

def run_experiment_mem(volumes, input_config):
    name = 'mem'
    file_name = '{}.json'.format(name)
    base_port = 8081
    apps = [1, 10]
    proc = None
    #proc = subprocess.Popen([os.path.join(SCRIPT_DIR, 'mem_analyzer.py'), str(base_port), 'out.f', str(apps[0])],
    #        stdout=subprocess.PIPE)
    with open(file_name, 'w') as f:
        experiment = {
            'language': 'python',
            'name': 'mem_single',
            'type': 'mem',
            'repetitions': 1,
            'disable_gc': False,
            'mem': {
                'participants' : apps[0],
                'analyzer_ip': 'localhost:{}'.format(base_port),
            }
        }
        volumes[os.path.join(output_dir, file_name)] = {
                'bind': os.path.join(HOME_DIR, file_name), 'mode': 'ro'
            }
        cfg_copy = copy.deepcopy(input_config)
        cfg_copy['benchmark'].update(experiment)
        json.dump(cfg_copy, f, indent=2)
    # make port an arg
    return [[name, partial(mem_clean, proc, base_port)]]

parser = argparse.ArgumentParser(description='Run local app experiments.')
parser.add_argument('benchmark', type=str, help='Benchmark name')
parser.add_argument('output_dir', type=str, help='Output dir')
parser.add_argument('language', choices=['python', 'nodejs', 'cpp'],
                    help='Benchmark language')
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

# 3. Prepare environment

# TurboBoost, disable HT, power cap, decide on which cores to use

# 4. Start storage instance

# 5. Upload data as required by benchmark

# 6. Create input for each experiment

# TODO: generate input
input_config = {'username' : 'testname', 'random_len' : 10}
benchmark_config = {}
benchmark_config['repetitions'] = args.repetitions
benchmark_config['disable_gc'] = True
input_config = { 'input' : input_config, 'benchmark' : benchmark_config }

client = docker.from_env()
volumes = {}
experiments = []
# time benchmark
#experiments.extend( run_experiment_time(volumes, input_config) )
# papi - IPC
#experiments.extend( run_experiment_papi_ipc(volumes, input_config) )
# mem analyzer
experiments.extend( run_experiment_mem(volumes, input_config) )

# Start measurement processes
for experiment, cleanup in experiments:

    # 7. Start docker instance with code and input
    container = run_container(client, volumes, os.path.join(output_dir, code_package))

    # 8. Run experiments
    exit_code, out = container.exec_run('/bin/bash run.sh {}.json'.format(experiment))
    print('Experiment: {} exit code: {}'.format(experiment, exit_code), file=output_file)
    if exit_code == 0:
        print(out.decode('utf-8'), file=output_file)
        #for line in out:
        #    print(line.decode('utf-8'), file=output_file)
    else:
        print('Experiment {} failed!'.format(experiment))
        print(exit_code)
        print(out)

    # 9. Copy result data
    os.makedirs(experiment, exist_ok=True)
    os.popen('docker cp {}:{} {}'.format(container.id, os.path.join(HOME_DIR, 'results'), experiment))
    os.popen('docker cp {}:{} {}'.format(container.id, os.path.join(HOME_DIR, 'logs'), experiment))

    cleanup()

    # 10. Kill docker instance
    #container.stop()

# mem
#cfg = run_experiment_mem(volumes, input_config)
#cfg['benchmark']['disable_gc'] = False
#cfg['benchmark']['repetitions'] = 1
#container = run_container(client, volumes, os.path.join(output_dir, code_package))

# Stop measurement processes

# Clean data storage

