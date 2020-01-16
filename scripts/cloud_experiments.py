#!python3


import argparse
import datetime
import importlib
import json
import sys
import traceback

from experiments_utils import *
from cache import cache

# TODO: replace with something more sustainable
sys.path.append(PROJECT_DIR)

parser = argparse.ArgumentParser(description='Run cloud experiments.')
parser.add_argument('benchmark', type=str, help='Benchmark name')
parser.add_argument('output_dir', type=str, help='Output dir')
parser.add_argument('size', choices=['test', 'small', 'large'],
                    help='Benchmark input test size')
parser.add_argument('config', type=str, help='Config JSON for experiments')
parser.add_argument('--deployment', choices=['azure','aws', 'local'],
                    help='Cloud to use')
parser.add_argument('--language', choices=['python', 'nodejs', 'cpp'],
                    default=None, help='Benchmark language')
parser.add_argument('--repetitions', action='store', default=5, type=int,
                    help='Number of experimental repetitions')
parser.add_argument('--cache', action='store', default='cache', type=str,
                    help='Cache directory')
parser.add_argument('--verbose', action='store', default=False, type=bool,
                    help='Verbose output')
args = parser.parse_args()

def prepare_input(client, benchmark, benchmark_path, size):
    # Look for input generator file in the directory containing benchmark
    sys.path.append(benchmark_path)
    mod = importlib.import_module('input')
    buckets = mod.buckets_count()
    storage = client.get_storage(benchmark, buckets, False)
    # Get JSON and upload data as required by benchmark
    input_config = mod.generate_input(size, storage.input(), storage.output(), storage.uploader_func)
    return input_config

# -1. Get provider config and create cloud object
experiment_config = json.load(open(args.config, 'r'))
systems_config = json.load(open(os.path.join(PROJECT_DIR, 'config', 'systems.json'), 'r'))
output_dir = None

cache_client = cache(args.cache)
docker_client = docker.from_env()
deployment_client = None


# CLI overrides JSON options
if args.language:
    experiment_config['experiments']['language'] = args.language
    language = args.language
else:
    language = experiment_config['experiments']['language']
if args.deployment:
    experiment_config['experiments']['deployment'] = args.cloud
    deployment = args.deployment
else:
    deployment = experiment_config['experiments']['deployment']

try:
    benchmark_summary = {}
    if language not in experiment_config[deployment]['runtime']:
        raise RuntimeError('Language {} is not supported on cloud {}'.format(language, args.cloud))
    experiment_config['experiments']['runtime'] = experiment_config[deployment]['runtime'][language]
    experiment_config['experiments']['region'] = experiment_config[deployment]['region']
    # Load cached secrets
    cached_config = cache_client.get_config(deployment)
    print(cached_config)
    if cached_config is not None:
        experiment_config[deployment].update(cached_config)
    print(experiment_config)
    # Create deployment client
    if deployment == 'aws':
        from cloud_frontend.aws import aws
        deployment_client = aws.aws(cache_client, experiment_config, language)
    else:
        from cloud_frontend.azure import azure
        deployment_client = azure.azure(experiment_config['azure'],
                language, docker_client)


    # 0. Input args
    args = parser.parse_args()
    verbose = args.verbose

    # 1. Create output dir
    output_dir = create_output(args.output_dir, args.verbose)
    logging.info('Created experiment output at {}'.format(args.output_dir))

    # 2. Locate benchmark
    benchmark_path = find_benchmark(args.benchmark)
    logging.info('Located benchmark {} at {}'.format(args.benchmark, benchmark_path))

    # 3. Build code package
    print(experiment_config)
    code_dir, code_size, config = create_code_package(docker_client,
            deployment_client, experiment_config['experiments'],
            args.benchmark, benchmark_path)
    logging.info('Created code_package {} of size {}'.format(code_dir, code_size))

    # 5. Prepare benchmark input
    input_config = prepare_input(deployment_client, args.benchmark, benchmark_path, args.size)
    input_config_bytes = json.dumps(input_config).encode('utf-8')

    # 6. Create function if it does not exist
    func = deployment_client.create_function(code_dir, args.benchmark,
            config['memory'], config['timeout'])

    # 7. Invoke!
    #ret = deployment_client.invoke(func, input_config_bytes)
    #print(ret)

    # get experiment and run
    

except Exception as e:
    print(e)
    traceback.print_exc()
    if output_dir:
        print('# Experiments failed! See {}/out.log for details'.format(output_dir))
finally:
    # Close
    if deployment_client is not None:
        deployment_client.shutdown()
    cache_client.shutdown()
