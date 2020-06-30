from sebs.faas.function import Function
import subprocess
import json
import requests
import os

class FissionFunction(Function):
    def __init__(self, name: str):
        super().__init__(name)

    def sync_invoke(self, payload: dict):
        #TODO:dokonczyc
        #functionUrl = os.environ['FISSION_ROUTER']
        url = "http://localhost:5051/benchmark"
        payload = json.dumps(payload)
        headers = {'content-type': "application/json"}
        response = requests.request("POST", url, data=payload, headers=headers)
        return response

    def async_invoke(self, payload: dict):
        raise Exception("Non-trigger invoke not supported!")
