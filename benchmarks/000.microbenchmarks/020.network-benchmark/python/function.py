import csv
import json
import socket
from datetime import datetime
from time import sleep

from . import storage

def handler(event):

    request_id = event['request-id']
    address = event['server-address']
    port = event['server-port']
    repetitions = event['repetitions']
    output_bucket = event.get('output-bucket')
    times = []
    i = 0
    socket.setdefaulttimeout(3)
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(('', 0))
    message = request_id.encode('utf-8')
    adr = (address, port)
    consecutive_failures = 0
    while i < repetitions + 1:
        try:
            send_begin = datetime.now().timestamp()
            server_socket.sendto(message, adr)
            msg, addr = server_socket.recvfrom(1024)
            recv_end = datetime.now().timestamp()
        except socket.timeout:
            i += 1
            consecutive_failures += 1
            if consecutive_failures == 5:
                print("Can't setup the connection")
                break
            continue
        if i > 0:
            times.append([i, send_begin, recv_end])
        i += 1
        consecutive_failures = 0
        server_socket.settimeout(2)
    server_socket.close()
   
    if consecutive_failures != 5:
        with open('/tmp/data.csv', 'w', newline='') as csvfile:
            writer = csv.writer(csvfile, delimiter=',')
            writer.writerow(["id", "client_send", "client_rcv"]) 
            for row in times:
                writer.writerow(row)
      
        client = storage.storage.get_instance()
        key = client.upload(output_bucket, 'results-{}.csv'.format(request_id), '/tmp/data.csv')

    return { 'result': key }
