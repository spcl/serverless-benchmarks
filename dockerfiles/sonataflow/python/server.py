import datetime
import os
import sys
import uuid

import bottle
from bottle import route, run, template, request

CODE_LOCATION='/function'

@route('/alive', method='GET')
def alive():
    return {
        "result": "ok"
    }

@route('/', method='POST')
def process_request():
    from function import function
    import traceback
    try:
        # SonataFlow sends requests wrapped in {"payload": ...}
        # Unwrap the payload before passing to the function
        request_data = request.json
        if isinstance(request_data, dict) and "payload" in request_data:
            function_input = request_data["payload"]
        else:
            function_input = request_data

        ret = function.handler(function_input)

        # Wrap response in payload if not already wrapped
        if isinstance(ret, dict) and "payload" in ret:
            return ret["payload"]
        return ret
    except Exception as e:
        print(f"Error processing request: {e}", file=sys.stderr)
        print(f"Request JSON: {request.json}", file=sys.stderr)
        traceback.print_exc()
        bottle.response.status = 500
        return {"error": str(e), "traceback": traceback.format_exc()}

sys.path.append(os.path.join(CODE_LOCATION))
sys.path.append(os.path.join(CODE_LOCATION, '.python_packages/lib/site-packages/'))
run(host='0.0.0.0', port=int(sys.argv[1]), debug=True)
