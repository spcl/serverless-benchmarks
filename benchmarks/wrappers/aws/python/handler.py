# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

import datetime, io, json, os, sys, uuid

# Add current directory to allow location of packages
sys.path.append(os.path.join(os.path.dirname(__file__), '.python_packages/lib/site-packages'))

container_id = None

# TODO: usual trigger
# implement support for S3 and others
def handler(event, context):
    global container_id

    income_timestamp = datetime.datetime.now().timestamp()

    # HTTP trigger with API Gateaway
    if 'body' in event:
        event = json.loads(event['body'])
    req_id = context.aws_request_id
    event['request-id'] = req_id
    event['income-timestamp'] = income_timestamp
    begin = datetime.datetime.now()
    from function import function
    ret = function.handler(event)
    end = datetime.datetime.now()

    log_data = ret
    if 'logs' in event:
        log_data['time'] = (end - begin) / datetime.timedelta(microseconds=1)
        results_begin = datetime.datetime.now()
        from function import storage
        storage_inst = storage.storage.get_instance()
        b = event.get('logs').get('bucket')
        storage_inst.upload_stream(b, '{}.json'.format(req_id),
                io.BytesIO(json.dumps(log_data).encode('utf-8')))
        results_end = datetime.datetime.now()
        results_time = (results_end - results_begin) / datetime.timedelta(microseconds=1)
    else:
        results_time = 0

    cold_start_var = ""
    if "cold_start" in os.environ:
        cold_start_var = os.environ["cold_start"]

    from function import environment
    env = environment.collect()
    if 'static' in env:
        container_id = str(uuid.uuid4())[0:8]

    return {
        'statusCode': 200,
        'body': json.dumps({
            'begin': begin.strftime('%s.%f'),
            'end': end.strftime('%s.%f'),
            'results_time': results_time,
            'is_cold': 'static' in env,
            'result': log_data,
            'request_id': context.aws_request_id,
            'cold_start_var': cold_start_var,
            'container_id': container_id,
            'environment': env,
        })
    }
