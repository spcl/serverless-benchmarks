

import datetime
import logging
import os
import json
import math

import collections

def recursive_visit(json_data: dict):

    print(json_data)
    if instance(json_data, collections.Mapping):
        for key, val in json_data.items():
            recursive_visit(val)

def get_results(deployment,experiment, output_dir):

    if deployment.name == 'aws':
        return get_results_aws(deployment,experiment, output_dir)


def process_results(result):

    requests = {}
    for repetition in result:
        for invocation in repetition:
            request_id = invocation['result']['response']['request_id']
            requests[request_id] = invocation
    return requests
     
def get_results_aws(deployment,experiment, output_dir):

    results = experiment['results']
    function_name = experiment['function_name']
    deployment_config = experiment['config']

    experiment_begin = experiment['begin']
    experiment_end = experiment['end']
    experiment_begin = int(math.floor(float(experiment_begin)))
    experiment_end = int(math.ceil(float(experiment_end)))
    #if args.end_time > 0:
    #    experiment_end = experiment_begin + args.end_time
    #else:
    #    experiment_end = int(datetime.datetime.now().timestamp())

    result_dir = os.path.join(output_dir, 'results')
    os.makedirs(result_dir, exist_ok=True)

    requests = process_results(results['cold'])
    requests = {**requests, **process_results(results['warm'])}
    print(len(requests))
    #print(json.dumps(requests, indent=2))

    # get results
    #requests = {}
    #for result_file in os.listdir(result_dir):
    #    # file name is ${request_id}.json
    #    request_id = os.path.splitext(os.path.basename(result_file))[0]
    #    with open(os.path.join(result_dir, result_file), 'rb') as binary_json:
    #        json_data = json.loads(binary_json.read().decode('utf-8'))
    #        requests[request_id] = json_data
    # get cloud logs
    deployment.download_metrics(function_name, deployment_config,
            experiment_begin, experiment_end, requests)
    #print(json.dumps(requests, indent=2))
    for key, val in requests.items():
        print(val)
        assert 'aws' in val
    print(len(requests))

