#!python3

import argparse
import datetime
import json
import os

from experiments_utils import *
from cache import cache

sys.path.append(PROJECT_DIR)

parser = argparse.ArgumentParser(description='Run cloud experiments.')
parser.add_argument('experiment_json', type=str, help='Path to JSON summarizing experiment.')
parser.add_argument('output_dir', type=str, help='Output dir')
parser.add_argument('--cache', action='store', default='cache', type=str,
                    help='cache directory')
parser.add_argument('--end-time', action='store', default='0', type=int,
                    help='Seconds to add to begin time for logs query. When 0 use current time.')
args = parser.parse_args()

experiment = json.load(open(args.experiment_json, 'r'))
deployment = experiment['config']['experiments']['deployment']
language = experiment['config']['experiments']['language']
cache_client = cache(args.cache)
docker_client = docker.from_env()
cached_config = cache_client.get_config(deployment)
experiment['config'][deployment].update(cached_config)

# Create deployment client
if deployment == 'aws':
    from cloud_frontend.aws import aws
    deployment_client = aws.aws(cache_client, experiment['config'],
            language, docker_client)
elif deployment == 'azure':
    from cloud_frontend.azure import azure
    deployment_client = azure.azure(cache_client, experiment['config'],
            language, docker_client)
else:
    from cloud_frontend.gcp import gcp
    deployment_client = gcp.gcp(cache_client, experiment['config'], language, docker_client)
storage_client = deployment_client.get_storage()

def recursive_visit(json_data: dict):

    for key, val in json_data.items():
        recursive_visit(val)


results = experiment['results']


function_name = experiment['experiment']['function_name']
deployment_config = experiment['config'][deployment]
experiment_begin = experiment['experiment']['begin']
if args.end_time > 0:
    experiment_end = experiment_begin + args.end_time
else:
    experiment_end = int(datetime.datetime.now().timestamp())

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
# get cloud logs
deployment_client.download_metrics(function_name, deployment_config,
        experiment_begin, experiment_end, requests)

with open(os.path.join(args.output_dir, 'results.json'), 'w') as out_f:
    json.dump(requests, out_f, indent=2)
