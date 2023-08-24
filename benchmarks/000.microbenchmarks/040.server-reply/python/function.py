import socket
from time import sleep
from jsonschema import validate

def handler(event):

    schema = {
        "type": "object",
        "required": ["ip-address", "port"],
        "properties": {
            "ip-address": {"type": "number"},
            "port": {"type": "integer"}
        }
    }
    try:
        validate(event, schema=schema)
    except:
        return { 'status': 'failure', 'result': 'Some value(s) is/are not found in JSON data or of incorrect type' }
    
    # start timing
    addr = (event['ip-address'], event['port'])
    
    socket.setdefaulttimeout(20)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(addr)
    msg = s.recv(1024).decode()
    return { 'status': 'success', 'result': 'Returned with no error', "measurement": msg }
