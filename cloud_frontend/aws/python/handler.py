
import datetime, os, sys

# Add current directory to allow location of packages
sys.path.append(os.path.join(os.path.dirname(__file__), '.python_packages/lib/site-packages'))


def handler(event, context):
    begin = datetime.datetime.now()
    # TODO: usual trigger
    # implement support for S3 and others
    from function import function
    ret = function.handler(event)
    end = datetime.datetime.now()
    return {
        "time" : (end - begin) / datetime.timedelta(microseconds=1),
        "message": ret
    }

    
