import os
import json
from . import storage


def handler(event):
    lst = event["list"]
    bucket = lst[0]["bucket"]
    prefix = lst[0]["prefix"]

    client = storage.storage.get_instance()
    dirs = client.list_directory(bucket, prefix)
    dirs = [p.split(os.sep)[1] for p in dirs]
    dirs = list(set(dirs))
    lst = [{
        "bucket": bucket,
        "dir": os.path.join(prefix, path)
    } for path in dirs]


    return {
        "list": lst
    }