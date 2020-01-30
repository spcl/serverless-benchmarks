
import datetime, io, json, os, sys

# Add current directory to allow location of packages
sys.path.append(os.path.join(os.path.dirname(__file__), '.python_packages/lib/site-packages'))

# TODO: usual trigger
# implement support for S3 and others
def handler(event, context):

    # HTTP trigger with API Gateaway
    if 'httpMethod' in event:
        print(event['body'])
        event = json.loads(event['body'])
    begin = datetime.datetime.now()
    from function import function
    ret = function.handler(event)
    end = datetime.datetime.now()

    log_data = {
        'result': ret['result']
    }
    if 'measurement' in ret:
        log_data['measurement'] = ret['measurement']
    if 'logs' in event:
        log_data['time'] = (end - begin) / datetime.timedelta(microseconds=1)
        results_begin = datetime.datetime.now()
        from function import storage
        storage_inst = storage.storage.get_instance()
        b = event.get('logs').get('bucket')
        req_id = context.aws_request_id
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

    return {
        'statusCode': 200,
        'body': json.dumps({
            'begin': begin.strftime('%s.%f'),
            'end': end.strftime('%s.%f'),
            'results_time': results_time,
            'is_cold': is_cold,
            'result': log_data
        })
    }

