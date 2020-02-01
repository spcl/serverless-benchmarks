

import datetime
import os
import json

def recursive_visit(json_data: dict):

    for key, val in json_data.items():
        recursive_visit(val)

def get_results(deployment,experiment, output_dir):

    if deployment.name == 'aws':
        return get_results_aws(deployment,experiment, output_dir)

     
def get_results_aws(deployment,experiment, output_dir):

    results = experiment['results']
    function_name = experiment['experiment']['function_name']
    deployment_config = experiment['config'][deployment]
    experiment_begin = experiment['experiment']['begin']
    if args.end_time > 0:
        experiment_end = experiment_begin + args.end_time
    else:
        experiment_end = int(datetime.datetime.now().timestamp())

    result_dir = os.path.join(output_dir, 'results')
    os.makedirs(result_dir, exist_ok=True)

    # get results
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

