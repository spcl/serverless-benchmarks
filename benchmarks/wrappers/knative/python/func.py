import logging
import datetime
import os
import uuid
from flask import jsonify
from parliament import Context
import minio


def main(context: Context):
    logging.getLogger().setLevel(logging.INFO)
    begin = datetime.datetime.now()  # Initialize begin outside the try block

    event = context.request.json
    logging.info(f"Received event: {event}")

    request_id = str(uuid.uuid4())  # Generate a unique request ID

    try:
        from function import function

        # Update the timestamp after extracting JSON data
        begin = datetime.datetime.now()
        # Pass the extracted JSON data to the handler function
        ret = function.handler(event)
        end = datetime.datetime.now()
        logging.info("Function result: {}".format(ret))
        log_data = {"result": ret["result"]}
        if "measurement" in ret:
            log_data["measurement"] = ret["measurement"]
        results_time = (end - begin) / datetime.timedelta(microseconds=1)

        is_cold = False
        fname = "cold_run"
        if not os.path.exists(fname):
            is_cold = True
            open(fname, "a").close()

        return {
            "request_id": request_id,
            "begin": begin.strftime("%s.%f"),
            "end": end.strftime("%s.%f"),
            "results_time": results_time,
            "is_cold": is_cold,
            "result": log_data,
        }

    except Exception as e:
        end = datetime.datetime.now()
        results_time = (end - begin) / datetime.timedelta(microseconds=1)
        logging.error(f"Error - invocation failed! Reason: {e}")
        return {
            "request_id": request_id,
            "begin": begin.strftime("%s.%f"),
            "end": end.strftime("%s.%f"),
            "results_time": results_time,
            "result": f"Error - invocation failed! Reason: {e}",
        }
