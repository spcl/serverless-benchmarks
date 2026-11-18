# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

import datetime, io, json, os, sys, time, uuid

# Add current directory to allow location of packages
sys.path.append(os.path.join(os.path.dirname(__file__), '.python_packages/lib/site-packages'))

def cold_test():
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
    return is_cold, container_id


def mcp_handler(message, context, income_timestamp):
    from function import mcp_shim

    # Every MCP request counts, so a call after initialize in a fresh container is warm.
    is_cold, container_id = cold_test()

    meta = {
        'income_timestamp': income_timestamp,
        'is_cold': is_cold,
        'container_id': container_id,
        'request_id': context.aws_request_id,
    }

    def call_tool(arguments):
        begin = datetime.datetime.now()
        cpu_begin = time.process_time()
        # The benchmark is imported on first use, so a fresh container's first call pays for it.
        import_begin = time.perf_counter()
        from function import function
        import_us = int((time.perf_counter() - import_begin) * 1e6)
        ret = function.handler(arguments)
        cpu_us = int((time.process_time() - cpu_begin) * 1e6)
        end = datetime.datetime.now()
        return ret, dict(meta, begin=begin.strftime('%s.%f'), end=end.strftime('%s.%f'),
                         cpu_us=cpu_us, import_us=import_us)

    response = mcp_shim.handle(message, call_tool, meta)
    if response is None:
        return {'statusCode': 202, 'body': ''}
    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'application/json'},
        'body': json.dumps(response),
    }

# TODO: usual trigger
# implement support for S3 and others
def handler(event, context):

    income_timestamp = datetime.datetime.now().timestamp()

    # HTTP trigger with API Gateaway
    if 'body' in event:
        event = json.loads(event['body'])

    # MCP Streamable HTTP: the body is a JSON-RPC message
    from function import mcp_shim
    if mcp_shim.is_mcp_message(event):
        return mcp_handler(event, context, income_timestamp)
    req_id = context.aws_request_id
    event['request-id'] = req_id
    event['income-timestamp'] = income_timestamp
    begin = datetime.datetime.now()
    cpu_begin = time.process_time()
    import_begin = time.perf_counter()
    from function import function
    import_us = int((time.perf_counter() - import_begin) * 1e6)
    ret = function.handler(event)
    cpu_us = int((time.process_time() - cpu_begin) * 1e6)
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

    is_cold, container_id = cold_test()

    cold_start_var = ""
    if "cold_start" in os.environ:
        cold_start_var = os.environ["cold_start"]

    return {
        'statusCode': 200,
        'body': json.dumps({
            'begin': begin.strftime('%s.%f'),
            'end': end.strftime('%s.%f'),
            'results_time': results_time,
            'is_cold': is_cold,
            'result': log_data,
            'request_id': context.aws_request_id,
            'cold_start_var': cold_start_var,
            'container_id': container_id,
            'cpu_us': cpu_us,
            'import_us': import_us,
        })
    }

