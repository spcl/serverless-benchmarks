#!python3

import argparse
import datetime
import importlib
import json
import sys
import traceback

from experiments_utils import *

parser = argparse.ArgumentParser(description='Run cloud experiments.')
parser.add_argument('cloud', choices=['azure','aws'], help='Cloud to use')
parser.add_argument('benchmark', type=str, help='Benchmark name')
parser.add_argument('output_dir', type=str, help='Output dir')
parser.add_argument('language', choices=['python', 'nodejs', 'cpp'],
                    help='Benchmark language')
parser.add_argument('size', choices=['test', 'small', 'large'],
                    help='Benchmark input test size')
parser.add_argument('config', type=str, help='Config JSON for provider')
parser.add_argument('--repetitions', action='store', default=5, type=int,
                    help='Number of experimental repetitions')
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
    input_config = mod.generate_input(size, storage.input_buckets, storage.output_buckets, storage.uploader_func)
    return input_config

def import_config(path):
    return json.load(open(path, 'r'))

# -1. Get provider config and create cloud object
experiment_config = json.load(open(args.config, 'r'))
systems_config = json.load(open(os.path.join(PROJECT_DIR, 'config', 'systems.json'), 'r'))
docker = docker.from_env()

if args.cloud == 'aws':
    from cloud_providers import aws
    client = aws(experiment_config[args.cloud], args.language)
else:
    # TODO:
    pass

try:
    benchmark_summary = {}
    benchmark_config = {}
    benchmark_config['language'] = args.language
    benchmark_config['runtime'] = experiment_config[args.cloud]['runtime'][args.language]
    benchmark_config['deployment'] = args.cloud

    # 0. Input args
    args = parser.parse_args()
    verbose = args.verbose

    # 1. Create output dir
    output_dir = create_output(args.output_dir, args.verbose)
    logging.info('# Created experiment output at {}'.format(args.output_dir))

    # 2. Locate benchmark
    benchmark_path = find_benchmark(args.benchmark)
    logging.info('# Located benchmark {} at {}'.format(args.benchmark, benchmark_path))

    # 3. Build code package
    code_package, code_size, config = create_code_package(docker, benchmark_config, args.benchmark, benchmark_path)
    logging.info('# Created code_package {} of size {}'.format(code_package, code_size))

    # 5. Prepare benchmark input
    input_config = prepare_input(client, args.benchmark, benchmark_path, args.size)
    input_config_bytes = json.dumps(input_config).encode('utf-8')

    # 6. Create function if it does not exist
    func = client.create_function(code_package, args.benchmark,
            config['memory'], config['timeout'])

    # 7. Invoke!
    ret = client.invoke(func, input_config_bytes)
    print(ret)

    # get experiment and run


except Exception as e:
    print(e)
    traceback.print_exc()
    print('# Experiments failed! See {}/out.log for details'.format(output_dir))
