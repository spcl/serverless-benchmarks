import csv
import socket
from datetime import datetime
from jsonschema import validate

from . import storage

def handler(event):

    schema = {
        "type": "object",
        "required": [ "request_id", "server-address", "server-port", "repetitions", "output-bucket" ],
        "properties": {
            "request-id": {"type": "integer"},
            "server-address": {"type": "integer"},
            "server-port": {"type": "integer"},
            "repetitions": {"type": "integer"},
            "output-bucket": {"type": "object"}
        }
    }
    try:
        validate(event, schema=schema)
    except:
        return { 'status': 'failure', 'result': 'Some value(s) is/are not found in JSON data or of incorrect type' }
    
    request_id = event['request-id']
    address = event['server-address']
    port = event['server-port']
    repetitions = event['repetitions']
    output_bucket = event['output-bucket']
    
    i = 0
    times = []
    socket.setdefaulttimeout(3)
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(('', 0))
    message = request_id.encode('utf-8')
    adr = (address, port)
    consecutive_failures = 0
    while i <= repetitions:
        try:
            send_begin = datetime.now().timestamp()
            server_socket.sendto(message, adr)
            msg, addr = server_socket.recvfrom(1024)
            recv_end = datetime.now().timestamp()
        except socket.timeout:
            i += 1
            consecutive_failures += 1
            if consecutive_failures == 5:
                server_socket.close()
                return { 'status': 'failure', 'result': 'Unable to setup connection' }
            continue
        if i > 0:
            times.append([i, send_begin, recv_end])
        i += 1
        consecutive_failures = 0
        server_socket.settimeout(2)
    server_socket.close()
   
    with open('/tmp/data.csv', 'w', newline='') as csvfile:
        writer = csv.writer(csvfile, delimiter=',')
        writer.writerow(["id", "client_send", "client_rcv"]) 
        for row in times:
            writer.writerow(row)
    
    client = storage.storage.get_instance()
    key = client.upload(output_bucket, f'results-{request_id}.csv', '/tmp/data.csv') 
    return { 'status': 'success', 'result': 'Returned with no error', 'measurement': key }
