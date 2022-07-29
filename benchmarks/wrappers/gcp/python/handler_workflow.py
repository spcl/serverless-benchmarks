
import datetime
import io
import json
import os
import sys
import uuid
import importlib

# Add current directory to allow location of packages
sys.path.append(os.path.join(os.path.dirname(__file__), '.python_packages/lib/site-packages'))

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


def handler(req):
    start = datetime.datetime.now().timestamp()
    os.environ["STORAGE_UPLOAD_BYTES"] = "0"
    os.environ["STORAGE_DOWNLOAD_BYTES"] = "0"

    event = req.get_json()

    full_function_name = os.getenv("FUNCTION_NAME")
    workflow_name, func_name = full_function_name.split("___")
    function = importlib.import_module(f"function.{func_name}")
    res = function.handler(event["payload"])

    end = datetime.datetime.now().timestamp()

    provider_request_id = req.headers.get("Function-Execution-Id")
    is_cold, container_id = probe_cold_start()
    payload = {
        "func": func_name,
        "start": start,
        "end": end,
        "is_cold": is_cold,
        "container_id": container_id,
        "provider.request_id": provider_request_id
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
