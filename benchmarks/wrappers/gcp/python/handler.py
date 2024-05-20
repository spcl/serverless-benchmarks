import base64, datetime, io, json, os, uuid, sys

from google.cloud import storage as gcp_storage

sys.path.append(os.path.join(os.path.dirname(__file__), '.python_packages/lib/site-packages'))

def handler_http(req):
    income_timestamp = datetime.datetime.now().timestamp()
    req_id = req.headers.get('Function-Execution-Id')


    req_json = req.get_json()
    req_json['request-id'] = req_id
    req_json['income-timestamp'] = income_timestamp
    begin = datetime.datetime.now()
    # We are deployed in the same directorygit status
    from function import function
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
        from function import storage
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
    fname = os.path.join('/tmp', 'cold_run')
    if not os.path.exists(fname):
        is_cold = True
        container_id = str(uuid.uuid4())[0:8]
        with open(fname, 'a') as f:
            f.write(container_id)
    else:
        with open(fname, 'r') as f:
            container_id = f.read()

    cold_start_var = ""
    if "cold_start" in os.environ:
        cold_start_var = os.environ["cold_start"]

    return json.dumps({
            'begin': begin.strftime('%s.%f'),
            'end': end.strftime('%s.%f'),
            'results_time': results_time,
            'is_cold': is_cold,
            'result': log_data,
            'request_id': req_id,
            'cold_start_var': cold_start_var,
            'container_id': container_id,
        }), 200, {'ContentType': 'application/json'}

def handler_queue(data, context):
    serialized_payload = data.get('data')
    payload = json.loads(base64.b64decode(serialized_payload).decode("utf-8"))

    from function import function
    ret = function.handler(payload)

    # TODO(oana)

def handler_storage(data, context):
    bucket_name = data.get('bucket')
    name = data.get('name')
    filepath = '/tmp/bucket_contents'

    from function import storage
    storage_inst = storage.storage.get_instance()
    storage_inst.download(bucket_name, name, filepath)

    payload = {}

    with open(filepath, 'r') as fp:
        payload = json.load(fp)

    from function import function
    ret = function.handler(payload)

    # TODO(oana)
