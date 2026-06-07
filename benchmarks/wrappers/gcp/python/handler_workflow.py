
import datetime
import json
import os
import sys
import uuid
import importlib

# Add current directory to allow location of packages
sys.path.append(os.path.join(os.path.dirname(__file__), '.python_packages/lib/site-packages'))

if 'NOSQL_STORAGE_DATABASE' in os.environ:
    from function import nosql

    nosql.nosql.get_instance(
        os.environ['NOSQL_STORAGE_DATABASE']
    )


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
    provider_request_id = (
        req.headers.get("X-Cloud-Trace-Context") or req.headers.get("Function-Execution-Id")
    )

    event = req.get_json(force=True)

    if isinstance(event, dict) and "payload" in event:
        func_payload = event["payload"]
        request_id = event.get("request_id", provider_request_id)
    elif isinstance(event, dict):
        request_id = event.pop("__request_id", provider_request_id)
        func_payload = event
    else:
        func_payload = event
        request_id = provider_request_id

    if isinstance(func_payload, dict):
        func_payload['request-id'] = provider_request_id

    full_function_name = os.getenv("MY_FUNCTION_NAME", "")
    if "--" in full_function_name:
        workflow_name, func_name = full_function_name.rsplit("--", 1)
    elif "___" in full_function_name:
        workflow_name, func_name = full_function_name.split("___", 1)
    else:
        workflow_name = full_function_name
        func_name = full_function_name

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
        "provider.request_id": provider_request_id,
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

    try:
        redis_host = os.getenv("REDIS_HOST", "")
        redis_password = os.getenv("REDIS_PASSWORD", "")
        if redis_host and redis_password:
            from redis import Redis
            redis_client = Redis(
                host=redis_host,
                port=6379,
                decode_responses=True,
                socket_connect_timeout=10,
                password=redis_password,
            )
            key = os.path.join(workflow_name, func_name, request_id, str(uuid.uuid4())[0:8])
            redis_client.set(key, json.dumps(measurement))
    except Exception:
        pass

    if isinstance(res, dict):
        res["__request_id"] = request_id

    return json.dumps(res), 200, {'Content-Type': 'application/json'}
