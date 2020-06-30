from flask import request, jsonify, current_app
from function import function
import json
def handler():
    body = request.get_data().decode("utf-8")
    current_app.logger.info("Body: " + body)
    event = json.loads(body)
    current_app.logger.info("Event: " + str(event))
    functionResult = function.handler(event)
    current_app.logger.info("Function result: " + str(functionResult))
    return jsonify(functionResult)
