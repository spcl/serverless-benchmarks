#!/usr/bin/python3

import argparse
import collections
import copy
import docker
import glob
import json
import minio
import os
import secrets
import subprocess
import sys
import traceback
import urllib, urllib.request
import uuid

from functools import partial
from typing import Tuple

from experiments_utils import *

def iterable(val):
    return val if isinstance(val, collections.Iterable) else [val, ]

def run_container(client, language, version, volumes, code_package, home_dir):
    return client.containers.run(
            'sebs.run.local.{}.{}'.format(language, version),
            command='/bin/bash',
            volumes = {
                **volumes,
                code_package : {'bind': os.path.join(home_dir, 'code.zip'), 'mode': 'ro'}
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

class docker_experiment:
    name = None
    experiment_type = None
    config = None
    instances = 0
    start = lambda *args: None
    cleanup = lambda * args: None
    finish = lambda *args: None
    docker_volumes = {}
    detach = False
    result_path = None
    json_file = None
    language = None

    # if more than one instance of app, then we need to detach from running containers
    def __init__(self, instances, name, experiment_type,
            input_config, option=None, additional_cfg=None):
        self.instances = instances
        self.detach = instances > 1
        self.experiment_type = experiment_type
        self.name = name
        self.language = input_config['benchmark']['language']

        self.json_file = '{}.json'.format(self.name)
        with open(self.json_file, 'w') as f:
            experiment = {
                'name': self.name,
                'type': self.experiment_type,
            }
            if option is not None:
                experiment['experiment_options'] = option
            cfg_copy = copy.deepcopy(input_config)
            cfg_copy['benchmark'].update(experiment)
            if additional_cfg is not None:
                cfg_copy['benchmark'].update(additional_cfg)
            json.dump(cfg_copy, f, indent=2)
            self.config = cfg_copy

    def get_docker_volumes(self, output_dir, home_dir):
        return {
                os.path.join(output_dir, self.json_file):
                {'bind': os.path.join(home_dir, self.json_file), 'mode': 'ro'}
            }

    # result is copied from Docker or created locally by analyzers
    # provide path to analyzer result OR find all csv files copied from Docker
    def get_result_path(self, instance):
        if self.result_path is None:
            path = os.path.join(instance, 'results')
            return [file for file in glob.glob(os.path.join(path, '*.csv'))]
        else:
            return [self.result_path]

class analyzer_experiment(docker_experiment):
    port = None
    proc = None

    def __init__(self, instances, name, experiment_type, input_config, port, option=None):
        additional_cfg = {
            'analyzer': {
                'participants' : instances,
                'analyzer_ip': 'localhost:{}'.format(port),
            }
        }
        docker_experiment.__init__(self, instances, name, experiment_type,
                input_config, option, additional_cfg)
        self.port = port

    # Start analyzer process on provided port.
    # Results are written to file at `result_path`
    # Output of analyzer goes to `file_output`
    def start(self):
        file_name = '{}.json'.format(self.name)
        os.makedirs(self.name, exist_ok=True)
        os.makedirs(os.path.join(self.name, 'results'), exist_ok=True)
        file_output = open(os.path.join(self.name, 'proc-analyzer.out'), 'w')
        self.result_path = os.path.join(self.name, 'results', '{}.csv'.format(self.name))
        self.proc = subprocess.Popen(
                [os.path.join(SCRIPT_DIR, 'proc_analyzer.py'), str(self.port),
                    self.result_path, self.experiment_type, str(self.instances)],
                stdout=file_output,
                stderr=subprocess.STDOUT
            )
        if self.proc.returncode is not None:
            logging.error('Memory analyzer finished unexpectedly')

    # Write down results of analyzer and kill the process.
    def cleanup(self):
        try:
            # curl returns zero event if request errored on server side
            response = urllib.request.urlopen('http://localhost:{}/dump'.format(self.port), {})
            code = response.getcode()
            if code != 200:
                logging.error('Proc analyzer failed when writing values!')
                logging.error(response.read())
                raise RuntimeError()
        except urllib.error.HTTPError as err:
            logging.error('Proc analyzer failed when writing values!')
            raise(err)
        self.proc.kill()

    # For launches with multiple instances, we need a way to tell if N-th
    # instance has been processed and we can launch a new one.
    # Thus we wait until server analyzer returns message indicating that all
    # current processing is finished.
    def finish(self, count):
        # verify if we can launch more instances (analyzer processed all active instances)
        if self.instances > 1:
            values = 0
            while values != count:
                response = urllib.request.urlopen('http://localhost:{}/processed_apps'.format(self.port), {})
                data = response.read()
                values = json.loads(data)['apps']

def run_experiment_time(input_config):
    experiments = []
    for option in ['warm', 'cold']:
        experiments.append(docker_experiment(
                instances=1,
                name='time_{}'.format(option),
                experiment_type='time',
                input_config=input_config,
                option=option
            ))
    return experiments

def run_experiment_papi_ipc(input_config):
    experiments = []
    experiments.append(docker_experiment(
        instances=1,
        name='ipc_papi',
        experiment_type='papi',
        input_config=input_config,
        additional_cfg={
            'papi': {
                'events': ['PAPI_TOT_CYC', 'PAPI_TOT_INS', 'PAPI_LST_INS'],
                'overflow_instruction_granularity' : 1e6,
                'overflow_buffer_size': 1e5
            }
        }
    ))
    return experiments
 
def run_experiment_mem(input_config):
    experiments = []
    experiments.append(analyzer_experiment(
        instances=1,
        name='mem-single',
        experiment_type='memory',
        input_config=input_config,
        port=8081
    ))
    experiments.append(analyzer_experiment(
        instances=10,
        name='mem-multiple',
        experiment_type='memory',
        input_config=input_config,
        port=8081
    ))
    return experiments

def run_experiment_disk_io(input_config):
    experiments = []
    experiments.append(analyzer_experiment(
        instances=1,
        name='disk-io',
        experiment_type='disk-io',
        input_config=input_config,
        port=8081
    ))
    return experiments

experiments = {
        'time' : run_experiment_time,
        'papi' : run_experiment_papi_ipc,
        'memory' : run_experiment_mem,
        'disk-io' : run_experiment_disk_io
        }
experiments['all'] = list(experiments.values())
docker_client = docker.from_env()
verbose = False

parser = argparse.ArgumentParser(description='Run local app experiments.')
parser.add_argument('benchmark', type=str, help='Benchmark name')
parser.add_argument('output_dir', type=str, help='Output dir')
parser.add_argument('language', choices=['python', 'nodejs', 'cpp'],
                    help='Benchmark language')
parser.add_argument('experiment', choices=['time', 'papi', 'memory', 'disk-io', 'all'],
                    help='Benchmark language')
parser.add_argument('size', choices=['test', 'small', 'large'],
                    help='Benchmark input test size')
parser.add_argument('--repetitions', action='store', default=5, type=int,
                    help='Number of experimental repetitions')
parser.add_argument('--config', action='store',
        default=os.path.join(SCRIPT_DIR, os.pardir, 'config', 'experiments.json'),
        type=str, help='Experiments config file')
parser.add_argument('--verbose', action='store', default=False, type=bool,
                    help='Verbose output')

class minio_storage:
    storage_container = None
    input_buckets = []
    output_buckets = []
    access_key = None
    secret_key = None
    port = 9000
    location = 'us-east-1'
    connection = None
    docker_client = None

    def __init__(self, docker_client, benchmark, buckets):
        self.docker_client = docker_client
        if buckets[0] + buckets[1] > 0:
            self.start()
            self.connection = self.get_connection()
            for i in range(0, buckets[0]):
                self.input_buckets.append(
                        self.create_bucket('{}-{}-input'.format(benchmark, i)))
            for i in range(0, buckets[1]):
                self.output_buckets.append(
                        self.create_bucket('{}-{}-output'.format(benchmark, i)))
    def input(self):
        return self.input_buckets
    
    def output(self):
        return self.output_buckets
             
    def start(self):
        self.access_key = secrets.token_urlsafe(32)
        self.secret_key = secrets.token_hex(32)
        logging.info('Starting minio instance at localhost:{}'.format(self.port))
        logging.info('ACCESS_KEY={}'.format(self.access_key))
        logging.info('SECRET_KEY={}'.format(self.secret_key))
        self.storage_container = self.docker_client.containers.run(
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
        if self.storage_container is not None:
            logging.info('Stopping minio instance at localhost:{}'.format(self.port))
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
            logging.info('Created bucket {}'.format(bucket_name))
            return bucket_name
        except (minio.error.BucketAlreadyOwnedByYou, minio.error.BucketAlreadyExists, minio.error.ResponseError) as err:
            logging.error('Bucket creation failed!')
            # rethrow
            raise err

    def uploader_func(self, bucket_idx, file, filepath):
        try:
            self.connection.fput_object(self.input_buckets[0], file, filepath)
        except minio.error.ResponseError as err:
            logging.error('Upload failed!')
            raise(err)

    def clean(self):
        for bucket in self.output_buckets:
            objects = self.connection.list_objects_v2(bucket)
            objects = [obj.object_name for obj in objects]
            for err in self.connection.remove_objects(bucket, objects):
                logging.error("Deletion Error: {}".format(del_err))

    def download_results(self, result_dir):
        result_dir = os.path.join(result_dir, 'storage_output')
        for bucket in self.output_buckets:
            objects = self.connection.list_objects_v2(bucket)
            objects = [obj.object_name for obj in objects]
            for obj in objects:
                self.connection.fget_object(bucket, obj, os.path.join(result_dir, obj))

class local:

    storage_instance = None
    docker_client = None

    def __init__(self, docker_client):
        self.docker_client = docker_client

    def package_code(self, dir, benchmark):
        cur_dir = os.getcwd()
        os.chdir(dir)
        # create zip
        execute(
            'zip -qur {}.zip *'.format(os.path.join(os.path.pardir, benchmark)),
            shell=True
        )
        par_dir = os.path.join(dir, os.path.pardir)
        logging.info('Created {}.zip archive'.format(os.path.join(par_dir, benchmark)))
        os.chdir(cur_dir)
        return os.path.join(par_dir, '{}.zip'.format(benchmark))

    '''
        Create wrapper object for minio storage and fill buckets.
        Starts minio as a Docker instance, using always fresh buckets.

        :param benchmark:
        :param buckets: number of input and output buckets
        :param replace_existing: not used.
        :return: Azure storage instance
    '''
    def get_storage(self, benchmark :str, buckets :Tuple[int, int],
            replace_existing: bool=False):
        self.storage_instance = minio_storage(docker_client, benchmark, buckets)
        return self.storage_instance

    def storage(self):
        return self.storage_instance

    def shutdown(self):
        self.storage().stop()

try:

    benchmark_summary = {}

    # 0. Input args
    args = parser.parse_args()
    verbose = args.verbose
    experiment_config = json.load(open(args.config, 'r'))
    systems_config = json.load(open(os.path.join(SCRIPT_DIR, os.pardir, 'config', 'systems.json'), 'r'))
    deployment_client = local(docker_client)

    # 1. Create output dir
    output_dir = create_output(args.output_dir, args.verbose)
    logging.info('# Created experiment output at {}'.format(args.output_dir))

    # Verify if the experiment is supported for the language
    supported_experiments = systems_config['local']['experiments'][args.language]
    if args.experiment != 'all':
        selected_experiments = [args.experiment]
    else:
        selected_experiments = list(experiments.keys())
        selected_experiments.remove('all')
    if any(val not in supported_experiments for val in selected_experiments):
        raise RuntimeError('Experiment {} is not supported for language {}!'.format(args.experiment, args.language))

    # 2. Locate benchmark
    benchmark_path = find_benchmark(args.benchmark, 'benchmarks')
    logging.info('# Located benchmark {} at {}'.format(args.benchmark, benchmark_path))

    # 6. Create experiment config
    benchmark_config = {}
    benchmark_config['repetitions'] = args.repetitions
    benchmark_config['disable_gc'] = True
    benchmark_config['language'] = args.language
    benchmark_config['runtime'] = experiment_config['local']['runtime'][args.language]
    benchmark_config['deployment'] = 'local'

    # 3. Build code package
    code_package, code_size, config = create_code_package(
            docker=docker_client,
            client=deployment_client,
            config=benchmark_config,
            benchmark=args.benchmark,
            benchmark_path=benchmark_path,
    )
    logging.info('# Created code_package {} of size {}'.format(code_package, code_size))

    # 4. Prepare environment
    # TurboBoost, disable HT, power cap, decide on which cores to use

    # 5. Prepare benchmark input
    input_config = prepare_input(deployment_client, args.benchmark,
            benchmark_path, args.size, False)
    storage_config = deployment_client.storage().config_to_json()
    if storage_config:
        benchmark_config['storage'] = storage_config
    app_config = {'name' : args.benchmark, 'size' : code_size}
    input_config = {
        'input' : input_config,
        'app': app_config,
        'benchmark' : benchmark_config,
        'experiment_config': experiment_config
    }

    # 7. Select experiments
    volumes = {}
    enabled_experiments = []
    for ex_func in iterable(experiments[args.experiment]):
        enabled_experiments.extend( ex_func(input_config) )

    # 8. Start measurement processes
    for experiment in enabled_experiments:

        home_dir = '/home/{}'.format(systems_config['local']['languages'][args.language]['username'])
        containers = [None] * experiment.instances
        os.makedirs(experiment.name, exist_ok=True)
        logging.info('# Experiment: {} begins.'.format(experiment.name))
        experiment.start()
        for i in range(0, experiment.instances):
            # 7. Start docker instance with code and input
            containers[i] = run_container(
                docker_client, args.language, benchmark_config['runtime'],
                {**volumes, **experiment.get_docker_volumes(output_dir, home_dir)},
                os.path.join(output_dir, code_package),
                home_dir
            )
       
            # 8. Run experiments
            exit_code, out = containers[i].exec_run('/bin/bash run.sh {}.json'.format(experiment.name), detach=experiment.detach)
            if not experiment.detach:
                logging.info('# Experiment: {} exit code: {}'.format(experiment.name, exit_code))
                if exit_code == 0:
                    logging.debug('Output: {}'.format(out.decode('utf-8')))
                else:
                    logging.error('# Experiment {} failed! Exit code {}'.format(experiment.name, exit_code))
                    logging.error(out.decode('utf-8'))
            else:
                experiment.finish(i+1)
                logging.info('Experiment: {} container {} finished.'.format(experiment.name, i))

        # Summarize experiment
        summary = {}
        summary['config'] = experiment.config
        summary['instances'] = []
        # 9. Copy result data
        for idx, container in enumerate(containers):
            dest_dir = os.path.join(experiment.name, 'instance_{}'.format(idx))
            os.makedirs(dest_dir, exist_ok=True)
            os.popen('docker cp {}:{} {}'.format(container.id, os.path.join(home_dir, 'results'), dest_dir))
            os.popen('docker cp {}:{} {}'.format(container.id, os.path.join(home_dir, 'logs'), dest_dir))

            # 10. Kill docker instance
            container.stop()

            # 11. Find experiment JSONs and include in summary
            result_path = os.path.join(dest_dir, 'results')
            jsons = [json_file for json_file in glob.glob(os.path.join(result_path, '*.json'))] 
            summary['instances'].append( {'config': jsons, 'results': experiment.get_result_path(dest_dir)} )

        benchmark_summary[experiment.name] = summary

        # 11. Cleanup active measurement processes
        experiment.cleanup()
        deployment_client.storage().download_results(experiment.name)
        deployment_client.storage().clean()

    # Summarize
    benchmark_summary['system'] = {}
    uname = os.uname()
    for val in ['nodename', 'sysname', 'release', 'version', 'machine']:
        benchmark_summary['system'][val] = getattr(uname, val)
    json.dump(benchmark_summary, open('experiments.json', 'w'), indent=2)

except Exception as e:
    print(e)
    logging.error(e)
    traceback.print_exc()
    print('# Experiments failed! See {}/out.log for details'.format(output_dir))
finally:
    deployment_client.shutdown()
