#!python3

import argparse
import json
import os

from experiments_utils import *
from cache import cache

sys.path.append(PROJECT_DIR)

parser = argparse.ArgumentParser(description='Run cloud experiments.')
parser.add_argument('experiment_json', type=str, help='Path to JSON summarizing experiment.')
parser.add_argument('output_dir', type=str, help='Output dir')
parser.add_argument('--cache', action='store', default='cache', type=str,
                    help='Cache directory')
args = parser.parse_args()

experiment = json.load(open(args.experiment_json, 'r'))
deployment = experiment['config']['experiments']['deployment']
language = experiment['config']['experiments']['language']
cache_client = cache(args.cache)
docker_client = docker.from_env()

# Create deployment client
if deployment == 'aws':
    from cloud_frontend.aws import aws
    deployment_client = aws.aws(cache_client, experiment['config'],
            language, docker_client)
else:
    from cloud_frontend.azure import azure
    deployment_client = azure.azure(cache_client, experiment['config'],
            language, docker_client)
storage_client = deployment_client.get_storage()

experiment_begin = experiment['experiment']['begin']
experiment_end = experiment['experiment']['end']

result_dir = os.path.join(args.output_dir, 'results')
os.makedirs(result_dir, exist_ok=True)

# get results
download_bucket(storage_client, experiment['experiment']['results_bucket'], result_dir)
requests = {}
for result_file in os.listdir(result_dir):
    # file name is ${request_id}.json
    request_id = os.path.splitext(os.path.basename(result_file))[0]
    with open(os.path.join(result_dir, result_file), 'rb') as binary_json:
        json_data = json.loads(binary_json.read().decode('utf-8'))
        requests[request_id] = json_data

with open(os.path.join(args.output_dir, 'results.json'), 'w') as out_f:
    json.dump(requests, out_f, indent=2)
