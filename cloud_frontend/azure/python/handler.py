
import datetime, json

import azure.functions as func

from . import function

# TODO: usual trigger
# implement support for blob and others
def main(req: func.HttpRequest) -> func.HttpResponse:
    begin = datetime.datetime.now()
    ret = function.handler(req.get_json())
    end = datetime.datetime.now()
    return func.HttpResponse(
        json.dumps({
                "time" : (end - begin) / datetime.timedelta(microseconds=1),
                "message": ret
        }),
        mimetype="application/json",
    )

    
