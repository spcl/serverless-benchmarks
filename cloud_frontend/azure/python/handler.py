
import datetime

import azure.functions as func

import function

# TODO: usual trigger
# implement support for blob and others
def handler(req: func.HttpRequest) -> func.HttpResponse
    begin = datetime.datetime.now()
    ret = function.handler(req.params)
    end = datetime.datetime.now()
    return func.HttpResponse(
        json.dumps({
                "time" : (end - begin) / datetime.timedelta(microseconds=1),
                "message": ret
        }),
        mimetype="application/json",
    )

    
