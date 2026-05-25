import datetime
import json
import os
import uuid
import importlib

import logging

import azure.functions as func
from redis import Redis

def probe_cold_start():
    is_cold = False
    fname = os.path.join("/tmp", "cold_run")
    if not os.path.exists(fname):
        is_cold = True
        container_id = str(uuid.uuid4())[0:8]
        with open(fname, "a") as f:
            f.write(container_id)
    else:
        with open(fname, "r") as f:
            container_id = f.read()

    return is_cold, container_id

def main(event, context: func.Context):
    start = datetime.datetime.now().timestamp()
    os.environ["STORAGE_UPLOAD_BYTES"] = "0"
    os.environ["STORAGE_DOWNLOAD_BYTES"] = "0"

    workflow_name = os.getenv("APPSETTING_WEBSITE_SITE_NAME")
    func_name = os.path.basename(os.path.dirname(__file__))

    # FIXME: sort out workflow and function request id
    #event["request-id"] = context.invocation_id
    # this only works on benchmarks where payload is dict
    event["payload"]["request-id"] = context.invocation_id

    module_name = f"{func_name}.{func_name}"
    module_path = f"{func_name}/{func_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    function = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(function)

    res = function.handler(event["payload"])

    end = datetime.datetime.now().timestamp()

    is_cold, container_id = probe_cold_start()
    payload = {
        "func": func_name,
        "start": start,
        "end": end,
        "is_cold": is_cold,
        "container_id": container_id,
        "provider.request_id": context.invocation_id
    }

    func_res = os.getenv("SEBS_FUNCTION_RESULT")
    if func_res:
        payload["result"] = json.loads(func_res)

    bytes_upload = os.getenv("STORAGE_UPLOAD_BYTES", 0)
    if bytes_upload:
        payload["blob.upload"] = int(bytes_upload)

    bytes_download = os.getenv("STORAGE_DOWNLOAD_BYTES", 0)
    if bytes_download:
        payload["blob.download"] = int(bytes_download)

    payload = json.dumps(payload)

    redis = Redis(host={{REDIS_HOST}},
          port=6379,
          decode_responses=True,
          socket_connect_timeout=10,
          password={{REDIS_PASSWORD}})

    req_id = event["request_id"]
    key = os.path.join(workflow_name, func_name, req_id, str(uuid.uuid4())[0:8])
    redis.set(key, payload)

    return res
