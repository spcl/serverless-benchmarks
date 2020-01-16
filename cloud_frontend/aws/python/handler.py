
import datetime


def handler(event, context):
    begin = datetime.datetime.now()
    # TODO: usual trigger
    # implement support for S3 and others
    import function
    ret = function.handler(event)
    end = datetime.datetime.now()
    return {
        "time" : (end - begin) / datetime.timedelta(microseconds=1),
        "message": ret
    }

    
