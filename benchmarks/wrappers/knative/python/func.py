import logging
import datetime
from flask import jsonify
from parliament import Context
from function import handler

def main(context: Context):
    logging.getLogger().setLevel(logging.INFO)
    begin = datetime.datetime.now()  # Initialize begin outside the try block
    
    try:
        # Extract JSON data from the request
        event = context.request.json

        # Update the timestamp after extracting JSON data
        begin = datetime.datetime.now()
        # Pass the extracted JSON data to the handler function
        ret = handler(event)
        end = datetime.datetime.now()
        logging.info(f"Function result: {ret}")
        results_time = (end - begin) / datetime.timedelta(microseconds=1)

        response = {
            "begin": begin.strftime("%s.%f"),
            "end": end.strftime("%s.%f"),
            "results_time": results_time,
            "result": ret,
        }

        return jsonify(response), 200

    except Exception as e:
        end = datetime.datetime.now()
        results_time = (end - begin) / datetime.timedelta(microseconds=1)
        logging.error(f"Error - invocation failed! Reason: {e}")
        response = {
            "begin": begin.strftime("%s.%f"),
            "end": end.strftime("%s.%f"),
            "results_time": results_time,
            "result": f"Error - invocation failed! Reason: {e}",
        }
        return jsonify(response), 500
