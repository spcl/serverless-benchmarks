import datetime
import os
import sys
import uuid

import bottle
from bottle import route, run, template, request

CODE_LOCATION='/function'

@route('/', method='POST')
def flush_log():
    begin = datetime.datetime.now()
    from function import function
    end = datetime.datetime.now()
    # FIXME: measurements?
    ret = function.handler(request.json)

    return {
        'begin': begin.strftime('%s.%f'),
        'end': end.strftime('%s.%f'),
        "request_id": str(uuid.uuid4()),
        "is_cold": False,
        "result": {
            "output": ret
        }
    }

sys.path.append(os.path.join(CODE_LOCATION))
sys.path.append(os.path.join(CODE_LOCATION, '.python_packages/lib/site-packages/'))
run(host='0.0.0.0', port=int(sys.argv[1]), debug=True)

