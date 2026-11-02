# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

import datetime, io, json, os, uuid

import azure.functions as func


if 'NOSQL_STORAGE_DATABASE' in os.environ:

    from . import nosql

    nosql.nosql.get_instance(
        os.environ['NOSQL_STORAGE_DATABASE'],
        os.environ['NOSQL_STORAGE_URL'],
        os.environ['NOSQL_STORAGE_CREDS']
    )

if 'STORAGE_CONNECTION_STRING' in os.environ:

    from . import storage
    client = storage.storage.get_instance(os.environ['STORAGE_CONNECTION_STRING'])

container_id = None

# TODO: usual trigger
# implement support for blob and others
def main(req: func.HttpRequest, context: func.Context) -> func.HttpResponse:
    global container_id
    income_timestamp = datetime.datetime.now().timestamp()
    req_json = req.get_json()

    req_json['request-id'] = context.invocation_id
    req_json['income-timestamp'] = income_timestamp
    begin = datetime.datetime.now()
    # We are deployed in the same directory
    from . import function
    ret = function.handler(req_json)
    end = datetime.datetime.now()

    log_data = ret
    if 'logs' in req_json:
        log_data['time'] = (end - begin) / datetime.timedelta(microseconds=1)
        results_begin = datetime.datetime.now()
        from . import storage
        storage_inst = storage.storage.get_instance()
        b = req_json.get('logs').get('bucket')
        req_id = context.invocation_id
        storage_inst.upload_stream(b, '{}.json'.format(req_id),
                io.BytesIO(json.dumps(log_data).encode('utf-8')))
        results_end = datetime.datetime.now()
        results_time = (results_end - results_begin) / datetime.timedelta(microseconds=1)
    else:
        results_time = 0

    from . import environment
    env = environment.collect()

    if 'static' in env:
        container_id = str(uuid.uuid4())[0:8]

    return func.HttpResponse(
        json.dumps({
            'begin': begin.strftime('%s.%f'),
            'end': end.strftime('%s.%f'),
            'results_time': results_time,
            'result': log_data,
            'is_cold': 'static' in env,
            'is_cold_worker': 'static' in env,
            'container_id': container_id,
            'environ_container_id': os.environ['CONTAINER_NAME'],
            'request_id': context.invocation_id,
            'environment': env,
        }),
        mimetype="application/json"
    )
