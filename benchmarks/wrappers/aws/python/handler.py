import datetime, io, json, os, sys, uuid

# Add current directory to allow location of packages
sys.path.append(os.path.join(os.path.dirname(__file__), '.python_packages/lib/site-packages'))

def handler(event, context):

    income_timestamp = datetime.datetime.now().timestamp()

    populate_env_vars(context)

    # Flag to indicate whether the measurements should be returned as an HTTP
    # response or via a result queue.
    return_http = True

    # Queue trigger
    if ("Records" in event and event["Records"][0]["eventSource"] == 'aws:sqs'):
        event = json.loads(event["Records"][0]["body"])

        return_http = False

    # Storage trigger
    if ("Records" in event and "s3" in event["Records"][0]):
        bucket_name = event["Records"][0]["s3"]["bucket"]["name"]
        file_name = event["Records"][0]["s3"]["object"]["key"]

        from function import storage
        storage_inst = storage.storage.get_instance()

        obj = storage_inst.get_object(bucket_name, file_name)
        event = json.loads(obj)

        return_http = False

    # HTTP trigger with API Gateaway
    if 'body' in event:
        event = json.loads(event['body'])

    # Run function and measure.
    req_id = context.aws_request_id
    event['request-id'] = req_id
    event['income-timestamp'] = income_timestamp
    begin = datetime.datetime.now()
    from function import function
    ret = function.handler(event)
    end = datetime.datetime.now()

    log_data = {
        'output': ret['result']
    }
    if 'fns_triggered' in ret and ret['fns_triggered'] > 0:
        log_data['fns_triggered'] = ret['fns_triggered']
    if 'parent_execution_id' in event:
        log_data['parent_execution_id'] = event['parent_execution_id']
    if 'measurement' in ret:
        log_data['measurement'] = ret['measurement']
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

    stats = json.dumps({
                'begin': begin.strftime('%s.%f'),
                'end': end.strftime('%s.%f'),
                'results_time': results_time,
                'is_cold': is_cold,
                'result': log_data,
                'request_id': context.aws_request_id,
                'cold_start_var': cold_start_var,
                'container_id': container_id,
            })

    # Send the results onwards.
    result_queue = os.getenv('RESULT_QUEUE')

    if (return_http or result_queue is None):
        # HTTP / library trigger, standalone function: return an HTTP response.
        return {
            'statusCode': 200,
            'body': stats
        }
    else:
        # Queue trigger, storage trigger, or application: write to a queue.
        from function import queue
        queue_client = queue.queue(result_queue)
        queue_client.send_message(stats)

def populate_env_vars(context):
    arn = context.invoked_function_arn.split(":")

    os.environ['REGION'] = arn[3]
    os.environ['ACCOUNT_ID'] = arn[4]
