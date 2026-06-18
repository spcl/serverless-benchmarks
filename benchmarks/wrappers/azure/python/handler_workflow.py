import datetime
import json
import os
import sys
import uuid
import importlib

import logging

import azure.functions as func
from redis import Redis

SEBS_USER_AGENT = "SeBS/1.2 (https://github.com/spcl/serverless-benchmarks) SeBS Benchmark Suite/1.2"


def patch_requests_user_agent():
    try:
        import requests
    except ImportError:
        return

    original_request = requests.api.request
    if getattr(original_request, "_sebs_user_agent_patched", False):
        return

    def patched_request(method, url, **kwargs):
        headers = dict(kwargs.get("headers") or {})
        header_names = {key.lower() for key in headers}
        if "user-agent" not in header_names:
            headers["User-Agent"] = SEBS_USER_AGENT
        kwargs["headers"] = headers
        return original_request(method, url, **kwargs)

    patched_request._sebs_user_agent_patched = True
    requests.api.request = patched_request
    requests.request = patched_request


patch_requests_user_agent()

if 'NOSQL_STORAGE_DATABASE' in os.environ:
    from . import nosql
    nosql.nosql.get_instance(
        os.environ['NOSQL_STORAGE_DATABASE'],
        os.environ['NOSQL_STORAGE_URL'],
        os.environ['NOSQL_STORAGE_CREDS']
    )
    sys.modules["nosql"] = nosql

if 'STORAGE_CONNECTION_STRING' in os.environ:
    from . import storage
    storage.storage.get_instance(os.environ['STORAGE_CONNECTION_STRING'])
    sys.modules["storage"] = storage

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

    event["payload"]["request-id"] = context.invocation_id

    current_dir = os.path.dirname(__file__)
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)
    parent_dir = os.path.dirname(current_dir)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    package = __package__ or func_name
    function = importlib.import_module(f"{package}.{func_name}")

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

    redis_host = {{REDIS_HOST}}
    redis_password = {{REDIS_PASSWORD}}
    if redis_host:
        redis = Redis(host=redis_host,
              port=6379,
              decode_responses=True,
              socket_connect_timeout=10,
              password=redis_password)

        req_id = event["request_id"]
        key = os.path.join(workflow_name, func_name, req_id, str(uuid.uuid4())[0:8])
        redis.set(key, payload)

    return res
