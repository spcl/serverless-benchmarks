
import socket
from time import sleep

def handler(event):

    # start timing
    addr = (event.get('ip-address'), event.get('port'))
    socket.setdefaulttimeout(20)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(addr)
    msg = s.recv(1024).decode()
    return { 'status': 'success', 'result': 'Returned with no error', "measurement": msg }
