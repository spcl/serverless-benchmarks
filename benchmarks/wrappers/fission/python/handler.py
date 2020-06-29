from flask import request, jsonify
from function import function
import json
def handler():
    body = request.get_data().decode("utf-8")
    stringDict = json.dumps(body)
    event = json.loads(stringDict)
    functionResult = function.handler(event)
    return jsonify(functionResult)
