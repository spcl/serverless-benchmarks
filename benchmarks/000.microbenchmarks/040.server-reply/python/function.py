import json
import logging
import socket
from queue import Queue, Empty
from time import sleep
from concurrent import futures
from threading import Thread

queue = None
finish = None

def receive_udp(server_socket):
    global finish
    while True:
        try:
            msg, addr = server_socket.recvfrom(1024*2)
            request = json.loads(msg.decode())
            queue.put((request, addr))
            print(f"Received message {request} from {addr}")
        except socket.timeout:
            print("didn't receive anything")
            break
    finish = True

def handler(event):
    
    logging.basicConfig(level=logging.DEBUG)
    global queue
    global finish
    queue = Queue()
    finish = False

    caller_address = (event["caller-address"], event["caller-port"])
    holepunching_address = (event["holepunching-address"], event["holepunching-port"])
    server_alive = event["keep-alive-time"]
    if server_alive > 0:
        socket.setdefaulttimeout(server_alive)
    function_id = event["function-id"]
    # perform write in the system
    message = b"processed write request"
    logging.info(f"Reply to {caller_address}")
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(("", 0))
    server_socket.sendto(
        json.dumps({"type": "register", "id": function_id}).encode(),
        holepunching_address,
    )
    server_socket.sendto(message, caller_address)
    if server_alive == 0:
        return {'result': None}

    # register yourself and open a port
    #server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    #server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    #msg, addr = server_socket.recvfrom(1024)
    #assert json.loads(msg.decode())["state"] == "OK"

    print("Start listening thread")
    t = Thread(target = receive_udp, args = (server_socket, ))
    t.start()
    # address = event['connector-address-port']
    # port = event['connector-port']
    # time = 0
    while not finish:
        try:
            request, addr = queue.get(block=True,timeout=1)
            if request['type'] == 'connect':
                addr = tuple(request['addr'])
                print(f"Connecting to {addr}")
                server_socket.sendto(b"hole punching packet", addr)
                #msg, addr = server_socket.recvfrom(1024*2)
                #server_socket.sendto(b"processed write request", addr)
                #print(f"Finished write request from {addr}")
            elif request['type'] == 'request':
                server_socket.sendto(b"processed write request", addr)
                print(f"Finished write request from {addr}")
            else:
                print(f"Other {request['type']}")
            
        except Empty:
            pass
    t.join()
    print("Done")
    # start timing
    return {'result': None}
