import os
import io
from . import storage


def count_words(lst):
    index = dict()
    for word in lst:
        if len(word) == 0:
            continue

        val = index.get(word, 0)
        index[word] = val + 1

    return index

def handler(event):
    benchmark_bucket = event["benchmark_bucket"]
    bucket = event["bucket"]
    blob = event["blob"]
    prefix = event["prefix"]

    client = storage.storage.get_instance()
    my_buffer = client.download_stream(benchmark_bucket, bucket + '/' + blob)
    words = bytes(my_buffer).decode("utf-8").split("\n")
 
    index = count_words(words)
    for word, count in index.items():
        data = io.BytesIO()
        data.write(str(count).encode("utf-8"))
        data.seek(0)

        #client.upload_stream(benchmark_bucket, os.path.join(bucket, prefix, word, blob), data)
        client.upload_stream(benchmark_bucket, os.path.join(prefix, word, blob), data)

    return event
