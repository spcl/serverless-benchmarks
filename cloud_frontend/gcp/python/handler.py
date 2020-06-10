import datetime, io, json, os, sys

sys.path.append(os.path.join(os.path.dirname(__file__), '.python_packages/lib/site-packages'))


def handler(req):
    req_json = req.get_json()
    begin = datetime.datetime.now()
    # We are deployed in the same directory
    from function import function
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
        from function import storage
        storage_inst = storage.storage.get_instance()
        b = req_json.get('logs').get('bucket')
        # FIXME: AWS and Azure have context for it. What to use here for filename?
        storage_inst.upload_stream(b, '{}.json'.format(results_begin),
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
        open(fname, 'a').close()

    return json.dumps({
            'begin': begin.strftime('%s.%f'),
            'end': end.strftime('%s.%f'),
            'results_time': results_time,
            'is_cold': is_cold,
            'result': log_data,
            # FIXME: As above
            'request_id': str(datetime.datetime.now())
        }), 200, {'ContentType': 'application/json'}
