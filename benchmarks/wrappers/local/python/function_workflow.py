import datetime
import importlib
import json
import os
import uuid

from redis import Redis


_FUNCTION_HANDLER = None


def _load_function_handler():
    global _FUNCTION_HANDLER
    if _FUNCTION_HANDLER:
        return _FUNCTION_HANDLER

    module_name = os.getenv("SEBS_WORKFLOW_MODULE")
    if not module_name:
        raise RuntimeError("Environment variable SEBS_WORKFLOW_MODULE is not set.")

    module = importlib.import_module(module_name)
    if not hasattr(module, "handler"):
        raise RuntimeError(f"Module {module_name} does not provide a handler(payload) function.")
    _FUNCTION_HANDLER = module.handler
    return _FUNCTION_HANDLER


def _extract_request_id(event):
    request_id = event.get("request_id")
    if request_id:
        return request_id
    payload = event.get("payload")
    if isinstance(payload, dict):
        return payload.get("request_id") or payload.get("request-id")
    return None


def _maybe_push_measurement(event, duration_start, duration_end):
    redis_host = os.getenv("SEBS_REDIS_HOST")
    if not redis_host:
        return

    workflow_name = os.getenv("SEBS_WORKFLOW_NAME", "workflow")
    func_name = os.getenv("SEBS_WORKFLOW_FUNC", "function")
    request_id = event["request_id"]

    payload = {
        "func": func_name,
        "start": duration_start,
        "end": duration_end,
        "is_cold": False,
        "container_id": os.getenv("HOSTNAME", "local"),
        "provider.request_id": request_id,
    }

    func_res = os.getenv("SEBS_FUNCTION_RESULT")
    if func_res:
        payload["result"] = json.loads(func_res)

    upload_bytes = os.getenv("STORAGE_UPLOAD_BYTES", "0")
    download_bytes = os.getenv("STORAGE_DOWNLOAD_BYTES", "0")
    if upload_bytes.isdigit():
        payload["blob.upload"] = int(upload_bytes)
    if download_bytes.isdigit():
        payload["blob.download"] = int(download_bytes)

    redis = Redis(
        host=redis_host,
        port=int(os.getenv("SEBS_REDIS_PORT", "6379")),
        decode_responses=True,
        socket_connect_timeout=10,
        password=os.getenv("SEBS_REDIS_PASSWORD"),
    )

    key = os.path.join(workflow_name, func_name, request_id, str(uuid.uuid4())[0:8])
    redis.set(key, json.dumps(payload))
    print(f"[workflow] stored measurement {key}")


def handler(event):
    """
    Entry point used by the local workflow containers. Expects events with
    {"payload": <input>, "request_id": "..."} format and returns the same
    structure expected by our workflow orchestrator.
    """

    if "payload" not in event:
        raise RuntimeError("Workflow invocation payload must include 'payload' key.")

    request_id = _extract_request_id(event) or str(uuid.uuid4())
    event["request_id"] = request_id
    payload = event["payload"]
    handler_fn = _load_function_handler()

    begin = datetime.datetime.now().timestamp()
    print(f"[workflow] handler input: {event}", flush=True)
    result = handler_fn(payload)
    end = datetime.datetime.now().timestamp()

    _maybe_push_measurement(event, begin, end)

    return {
        "request_id": request_id,
        "payload": result,
    }
