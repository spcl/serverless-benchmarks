
import base64
import datetime, io, json, logging, os, uuid

from azure.identity import ManagedIdentityCredential
from azure.storage.queue import QueueClient

import azure.functions as func


def handler_http(req: func.HttpRequest, context: func.Context) -> func.HttpResponse:
    income_timestamp = datetime.datetime.now().timestamp()

    req_json = req.get_json()
    if 'connection_string' in req_json:
        os.environ['STORAGE_CONNECTION_STRING'] = req_json['connection_string']

    req_json['request-id'] = context.invocation_id
    req_json['income-timestamp'] = income_timestamp

    return func.HttpResponse(measure(req_json), mimetype="application/json")

def handler_queue(msg: func.QueueMessage, context: func.Context):
    income_timestamp = datetime.datetime.now().timestamp()

    logging.info('Python queue trigger function processed a queue item.')
    payload = msg.get_json()

    payload['request-id'] = context.invocation_id
    payload['income-timestamp'] = income_timestamp

    stats = measure(payload)

    queue_name = f"{os.getenv('WEBSITE_SITE_NAME')}-result"
    storage_account = os.getenv('STORAGE_ACCOUNT')
    logging.info(queue_name)
    logging.info(storage_account)

    from . import queue
    queue_client = queue.queue(queue_name, storage_account)
    queue_client.send_message(stats)

def handler_storage(blob: func.InputStream, context: func.Context):
    income_timestamp = datetime.datetime.now().timestamp()

    logging.info('Python Blob trigger function processed %s', blob.name)
    payload = json.loads(blob.readline().decode('utf-8'))
    
    payload['request-id'] = context.invocation_id
    payload['income-timestamp'] = income_timestamp

    stats = measure(payload)

    queue_name = f"{os.getenv('WEBSITE_SITE_NAME')}-result"
    storage_account = os.getenv('STORAGE_ACCOUNT')
    logging.info(queue_name)
    logging.info(storage_account)

    from . import queue
    queue_client = queue.queue(queue_name, storage_account)
    queue_client.send_message(stats)

# Contains generic logic for gathering measurements for the function at hand,
# given a request JSON. Used by all handlers, regardless of the trigger.
def measure(req_json) -> str:
    req_id = req_json['request-id']

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

    return json.dumps({
            'begin': begin.strftime('%s.%f'),
            'end': end.strftime('%s.%f'),
            'results_time': results_time,
            'result': log_data,
            'is_cold': is_cold,
            'is_cold_worker': is_cold_worker,
            'container_id': container_id,
            'environ_container_id': os.environ['CONTAINER_NAME'],
            'request_id': req_id
        })