import datetime
import io
import json
import os
import sys
import uuid
import importlib

# Add current directory to allow location of packages
sys.path.append(os.path.join(os.path.dirname(__file__), ".python_packages/lib/site-packages"))

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


def handler(event, context):
    start = datetime.datetime.now().timestamp()
    os.environ["STORAGE_UPLOAD_BYTES"] = "0"
    os.environ["STORAGE_DOWNLOAD_BYTES"] = "0"

    req_id = context.aws_request_id

    if isinstance(event, dict) and "payload" in event:
        func_payload = event["payload"]
        request_id = event.get("request_id", req_id)
    elif isinstance(event, dict):
        request_id = event.pop("__request_id", req_id)
        func_payload = event
    else:
        func_payload = event
        request_id = req_id

    workflow_name, func_name = context.function_name.split("___")
    function = importlib.import_module(f"function.{func_name}")
    res = function.handler(func_payload)

    end = datetime.datetime.now().timestamp()

    is_cold, container_id = probe_cold_start()
    measurement = {
        "func": func_name,
        "start": start,
        "end": end,
        "is_cold": is_cold,
        "container_id": container_id,
        "provider.request_id": context.aws_request_id,
    }

    func_res = os.getenv("SEBS_FUNCTION_RESULT")
    if func_res:
        measurement["result"] = json.loads(func_res)

    bytes_upload = os.getenv("STORAGE_UPLOAD_BYTES", 0)
    if bytes_upload:
        measurement["blob.upload"] = int(bytes_upload)

    bytes_download = os.getenv("STORAGE_DOWNLOAD_BYTES", 0)
    if bytes_download:
        measurement["blob.download"] = int(bytes_download)

    measurement_json = json.dumps(measurement)

    try:
        redis = Redis(
            host={{REDIS_HOST}},
            port=6379,
            decode_responses=True,
            socket_connect_timeout=10,
            password={{REDIS_PASSWORD}},
        )

        key = os.path.join(workflow_name, func_name, request_id, str(uuid.uuid4())[0:8])
        redis.set(key, measurement_json)
    except Exception:
        pass

    if isinstance(res, dict):
        res["__request_id"] = request_id
    return res
