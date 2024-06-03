
import base64
import datetime, io, json, logging, os, uuid

import azure.functions as func


def handler_http(req: func.HttpRequest, context: func.Context) -> func.HttpResponse:
    income_timestamp = datetime.datetime.now().timestamp()
    req_json = req.get_json()
    if 'connection_string' in req_json:
        os.environ['STORAGE_CONNECTION_STRING'] = req_json['connection_string']
    req_json['request-id'] = context.invocation_id
    req_json['income-timestamp'] = income_timestamp
    begin = datetime.datetime.now()
    # We are deployed in the same directory
    from . import function
    ret = function.handler(req_json)
    end = datetime.datetime.now()

    log_data = {
        'output': ret['result']
    }
    if 'measurement' in ret:
        log_data['measurement'] = ret['measurement']
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

    # cold test
    is_cold = False
    fname = os.path.join('/tmp','cold_run')
    if not os.path.exists(fname):
        is_cold = True
        container_id = str(uuid.uuid4())[0:8]
        with open(fname, 'a') as f:
            f.write(container_id)
    else:
        with open(fname, 'r') as f:
            container_id = f.read()

    is_cold_worker = False
    global cold_marker
    try:
        _ = cold_marker
    except NameError:
        cold_marker = True
        is_cold_worker = True

    return func.HttpResponse(
        json.dumps({
            'begin': begin.strftime('%s.%f'),
            'end': end.strftime('%s.%f'),
            'results_time': results_time,
            'result': log_data,
            'is_cold': is_cold,
            'is_cold_worker': is_cold_worker,
            'container_id': container_id,
            'environ_container_id': os.environ['CONTAINER_NAME'],
            'request_id': context.invocation_id
        }),
        mimetype="application/json"
    )

def handler_queue(msg: func.QueueMessage):
    logging.info('Python queue trigger function processed a queue item.')
    payload = msg.get_body().decode('utf-8')

    from . import function
    ret = function.handler(payload)

    # TODO(oana)

def handler_storage(blob: func.InputStream):
    logging.info('Python Blob trigger function processed %s', blob.name)
    payload = blob.readline().decode('utf-8')  # TODO(oana)
    
    from . import function
    ret = function.handler(payload)

    # TODO(oana)
