
import datetime, json, os

import azure.functions as func


# TODO: usual trigger
# implement support for blob and others
def main(req: func.HttpRequest) -> func.HttpResponse:
    req_json = req.get_json()
    if 'connection_string' in req_json:
        os.environ['STORAGE_CONNECTION_STRING'] = req_json['connection_string']
    begin = datetime.datetime.now()
    # We are deployed in the same directory
    from . import function
    ret = function.handler(req_json)
    end = datetime.datetime.now()
    return func.HttpResponse(
        json.dumps({
                "time" : (end - begin) / datetime.timedelta(microseconds=1),
                "message": ret
        }),
        mimetype="application/json",
    )

    
