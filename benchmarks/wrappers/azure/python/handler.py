
import datetime, io, json, os

import azure.functions as func


# TODO: usual trigger
# implement support for blob and others
def main(req: func.HttpRequest, context: func.Context) -> func.HttpResponse:
    req_json = req.get_json()
    if 'connection_string' in req_json:
        os.environ['STORAGE_CONNECTION_STRING'] = req_json['connection_string']
    begin = datetime.datetime.now()
    # We are deployed in the same directory
    from . import function
    ret = function.handler(req_json)
    end = datetime.datetime.now()

    log_data = {
        'result': ret['result']
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
        open(fname, 'a').close()

    return func.HttpResponse(
        json.dumps({
            'begin': begin.strftime('%s.%f'),
            'end': end.strftime('%s.%f'),
            'results_time': results_time,
            'result': log_data,
            'is_cold': is_cold,
            'environ': list(os.environ.items()),
            'request_id': context.invocation_id
        }),
        mimetype="application/json"
    )

