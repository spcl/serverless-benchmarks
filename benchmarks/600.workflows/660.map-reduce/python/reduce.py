import os
import io
import json
from . import storage


def handler(event):
    bucket = event["bucket"]
    path = event["dir"]

    client = storage.storage.get_instance()
    count = 0
    #each blob is one word.
    #for blob in client.list_directory(bucket, path):
    for blob in client.list_directory(bucket, path):
        my_buffer = client.download_stream(bucket, blob)
        count += int(bytes(my_buffer).decode("utf-8"))
        #count += int(my_buffer.getvalue().decode("utf-8"))

    return {
        "word": os.path.basename(path),
        "count": count
    }
