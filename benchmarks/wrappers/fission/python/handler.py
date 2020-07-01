from flask import request, jsonify, current_app

import json, datetime
def handler():
    body = request.get_data().decode("utf-8")
    current_app.logger.info("Body: " + body)
    event = json.loads(body)
    current_app.logger.info("Event: " + str(event))
    begin = datetime.datetime.now()
    from function import function
    ret = function.handler(event)
    end = datetime.datetime.now()
    current_app.logger.info("Function result: " + str(ret))
    log_data = {
        'result': ret['result']
    }
    if 'measurement' in ret:
        log_data['measurement'] = ret['measurement']
    results_time = 0
    # how to check it? 
    is_cold = False
    return jsonify(
        json.dumps({
            'begin': begin.strftime('%s.%f'),
            'end': end.strftime('%s.%f'),
            'results_time': results_time,
            'is_cold': is_cold,
            'result': log_data  
    }))
    
