import os
import json
import datetime
import uuid

import azure.functions as func
import azure.durable_functions as df


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


async def main(req: func.HttpRequest, starter: str, context: func.Context) -> func.HttpResponse:
    event = req.get_json()

    begin = datetime.datetime.now()

    client = df.DurableOrchestrationClient(starter)
    instance_id = await client.start_new("run_workflow", None, event)
    res = await client.wait_for_completion_or_create_check_status_response(req, instance_id, 1000000)

    end = datetime.datetime.now()

    is_cold, container_id = probe_cold_start()
    status_body = json.loads(res.get_body())
    code = 500 if status_body.get("runtimeStatus") == "Failed" else 200
    body = {
        "begin": begin.strftime("%s.%f"),
        "end": end.strftime("%s.%f"),
        "is_cold": is_cold,
        "container_id": container_id,
        "request_id": context.invocation_id,
        **status_body
    }

    return func.HttpResponse(
        status_code=code,
        body=json.dumps(body),
        mimetype="application/json"
    )