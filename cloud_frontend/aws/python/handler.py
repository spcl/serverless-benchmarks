
import datetime, io, json, os, sys

# Add current directory to allow location of packages
sys.path.append(os.path.join(os.path.dirname(__file__), '.python_packages/lib/site-packages'))


# TODO: usual trigger
# implement support for S3 and others
def handler(event, context):
    begin = datetime.datetime.now()
    from function import function
    ret = function.handler(event)
    end = datetime.datetime.now()

    if 'logs' in event:
        results_begin = datetime.datetime.now()
        from function import storage
        storage_inst = storage.storage.get_instance()
        b = event.get('logs').get('bucket')
        req_id = context.aws_request_id
        log_data = {
            'time': (end - begin) / datetime.timedelta(microseconds=1),
            'result': ret['result']
        }
        if 'measurement' in ret:
            log_data['measurement'] = ret['measurement']
        storage_inst.upload_stream(b, '{}.json'.format(req_id),
                io.BytesIO(json.dumps(log_data).encode('utf-8')))
        results_end = datetime.datetime.now()
        results_time = (results_end - results_begin) / datetime.timedelta(microseconds=1)
    else:
        results_time = 0

    return {
        'compute_time': (end - begin) / datetime.timedelta(microseconds=1),
        'results_time': results_time,
        'result': ret['result']
    }

