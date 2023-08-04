import csv
import json
import socket
from datetime import datetime
from time import sleep
from jsonschema import validate

from . import storage

def handler(event):

    schema = {
        "type": "object",
        "required": [ "request_id", "server-address", "server-port", "repetitions", "output-bucket", "income-timestamp" ],
        "properties": {
            "request-id": {"type": "integer"},
            "server-address": {"type": "integer"},
            "server-port": {"type": "integer"},
            "repetitions": {"type": "integer"},
            "output-bucket": {"type": "object"},
            "income-timestamp": {"type": "number"}
        }
    }
    try:
        validate(event, schema=schema)
    except:
        # !? To return 'measurement': {'bucket-key': None, 'timestamp': event['income-timestamp']}
        return { 'status': 'failure', 'result': 'Some value(s) is/are not found in JSON data or of incorrect type' }
    
    request_id = event['request-id']
    address = event['server-address']
    port = event['server-port']
    repetitions = event['repetitions']
    output_bucket = event['output-bucket']

    i = 0
    times = []
    print(f"Starting communication with {address}:{port}")
    socket.setdefaulttimeout(4)
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(('', 0))
    message = request_id.encode('utf-8')
    adr = (address, port)
    consecutive_failures = 0
    measurements_not_smaller = 0
    cur_min = 0
    while i < 1000:
        try:
            send_begin = datetime.now().timestamp()
            server_socket.sendto(message, adr)
            msg, addr = server_socket.recvfrom(1024)
            recv_end = datetime.now().timestamp()
        except socket.timeout:
            i += 1
            consecutive_failures += 1
            if consecutive_failures == 7:
                server_socket.close()
                # !? To return 'measurement': {'bucket-key': None, 'timestamp': event['income-timestamp']}
                return { 'status': 'failure', 'result': 'Unable to setup connection' }
            continue
        if i > 0:
            times.append([i, send_begin, recv_end])
        cur_time = recv_end - send_begin
        print(f"Time {cur_time} Min Time {cur_min} NotSmaller {measurements_not_smaller}")
        if cur_time > cur_min > 0:
            measurements_not_smaller += 1
            if measurements_not_smaller == repetitions:
                message = "stop".encode('utf-8')
                server_socket.sendto(message, adr)
                break
        else:
            cur_min = cur_time
            measurements_not_smaller = 0
        i += 1
        consecutive_failures = 0
        server_socket.settimeout(4)
    server_socket.close()
   
    with open('/tmp/data.csv', 'w', newline='') as csvfile:
        writer = csv.writer(csvfile, delimiter=',')
        writer.writerow(["id", "client_send", "client_rcv"]) 
        for row in times:
            writer.writerow(row)
    
    client = storage.storage.get_instance()
    key = client.upload(output_bucket, f'results-{request_id}.csv', '/tmp/data.csv')

    return { 'status': 'success', 'result': 'Returned with no error', 'measurement': {'bucket-key': key, 'timestamp': event['income-timestamp']} }
