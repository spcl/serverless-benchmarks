#!/usr/bin/env python3

import json
import logging
import socket
import sys
from threading import RLock
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Tuple


class ServerState:

    class FunctionState:
        def __init__(self, address: Tuple[str, int]):
            # FIXME - background thread doing heartbeats
            self.last_heartbeat: int = 0
            self.address: str = address[0]
            self.port: int = address[1]

    def __init__(self, port:int):
        self.active_functions: Dict[str, ServerState.FunctionState] = {}
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        #self.send_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        #self.send_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_address = ""
        self.socket.bind((server_address, port))
        #self.send_socket.bind((server_address, port))
        self.lock = RLock()

    def register_new_function(self, address: Tuple[str, int], func_id: str):

        if func_id in self.active_functions:
            logging.info(f"Overriding func {func_id}")
        with self.lock:
            logging.info(f"Registering function {func_id}")
            self.active_functions[func_id] = ServerState.FunctionState(address)
        # sockets are not thread safe - must use lock
        self.socket.sendto(json.dumps({"type": "holepuncher"}).encode(), address)

    def connect_function(self, address: Tuple[str, int], func_id: str):
        function_state = self.active_functions.get(func_id)
        if not function_state:
            logging.info(f"Unknown function {func_id}")
            self.socket.sendto(json.dumps({"state": "NOT_OK"}).encode(), address)
            return
        function_address = (function_state.address, function_state.port)
        #with self.lock:
        logging.info(f"Notify function {func_id} ({function_address}) about connection to {address}")
        self.socket.sendto(
            json.dumps({"type": "connect", "addr": address}).encode(),
            function_address,
        )
        self.socket.sendto(
            json.dumps({"type": "holepuncher", "state": "OK", "addr": function_address}).encode(), address
        )

def handle_request(data: dict, address: Tuple[str, int], state: ServerState):

    if data["type"] == "register":
        state.register_new_function(address, data["id"])
    elif data["type"] == "connect":
        state.connect_function(address, data["id"])
    else:
        logging.info("Unknown option")

def future_handler(future):
    try:
        future.result()
    except Exception:
        logging.exception("Request handling failed!")

def server_loop(state: ServerState):

    with ThreadPoolExecutor(max_workers=4) as executor:
        while True:
            data, address = state.socket.recvfrom(1024)
            logging.info(f"Request from {address}")
            data_json = json.loads(data.decode("utf-8"))
            if data_json["type"] == "quit":
                break
            f = executor.submit(handle_request, data_json, address, state)
            f.add_done_callback(future_handler)
        logging.info("Waiting for finish!")
        executor.shutdown()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from requests import get

    port = int(sys.argv[1])
    ip = get("http://checkip.amazonaws.com/").text.rstrip()
    logging.info(f"Serving UDP hole punching for functions at {ip}:{port}")
    state = ServerState(port)
    server_loop(state)
    logging.info("Finished serving!")
