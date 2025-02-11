import os
import json
from . import storage


def handler(event):
    lst = event["list"]
    benchmark_bucket = lst[0]["benchmark_bucket"]
    bucket = lst[0]["bucket"]
    prefix = lst[0]["prefix"]

    client = storage.storage.get_instance()
    dirs = client.list_directory(benchmark_bucket, prefix)
    dirs = [p.split(os.sep)[1] for p in dirs]
    dirs = list(set(dirs))
    lst = [{
        "bucket": benchmark_bucket,
        #"dir": os.path.join(bucket, prefix, path)
        #TODO add word here.
        "dir": os.path.join(prefix, path)
        #"dir": os.path.join(bucket, prefix)
    } for path in dirs]


    return {
        "list": lst
    }
