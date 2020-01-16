
import datetime, json, os

import azure.functions as func


# TODO: usual trigger
# implement support for blob and others
def main(req: func.HttpRequest) -> func.HttpResponse:
    req_json = req.get_json()
    os.environ['STORAGE_CONNECTION_STRING'] = req_json['connection_string']
    from . import function
    begin = datetime.datetime.now()
    ret = function.handler(req_json)
    end = datetime.datetime.now()
    return func.HttpResponse(
        json.dumps({
                "time" : (end - begin) / datetime.timedelta(microseconds=1),
                "message": ret
        }),
        mimetype="application/json",
    )

    
