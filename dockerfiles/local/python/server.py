import datetime
import json
import os
import sys
import uuid

import bottle
from bottle import route, run, template, request, response

CODE_LOCATION='/function'
# Each container runs one server process, so its first request is a cold start
cold_start = True

@route('/alive', method='GET')
def alive():
    return {
        "result:" "ok"
    }

@route('/', method='POST')
def process_request():
    global cold_start
    is_cold, cold_start = cold_start, False
    begin = datetime.datetime.now()
    from function import function
    end = datetime.datetime.now()
    # FIXME: measurements?
    ret = function.handler(request.json)

    return {
        'begin': begin.strftime('%s.%f'),
        'end': end.strftime('%s.%f'),
        "request_id": str(uuid.uuid4()),
        "is_cold": is_cold,
        "result": ret
    }

@route('/mcp', method='POST')
def process_mcp_request():
    global cold_start
    is_cold, cold_start = cold_start, False
    from function import mcp_shim
    meta = {'request_id': str(uuid.uuid4()), 'is_cold': is_cold}

    def call_tool(arguments):
        begin = datetime.datetime.now()
        from function import function
        ret = function.handler(arguments)
        end = datetime.datetime.now()
        return ret, dict(meta, begin=begin.strftime('%s.%f'), end=end.strftime('%s.%f'))

    try:
        message = json.loads(request.body.read())
    except ValueError:
        message = None
    response_msg = mcp_shim.handle(message, call_tool, meta)
    if response_msg is None:
        response.status = 202
        return ''
    response.content_type = 'application/json'
    return json.dumps(response_msg)

sys.path.append(os.path.join(CODE_LOCATION))
sys.path.append(os.path.join(CODE_LOCATION, '.python_packages/lib/site-packages/'))
run(host='0.0.0.0', port=int(sys.argv[1]), debug=True)

