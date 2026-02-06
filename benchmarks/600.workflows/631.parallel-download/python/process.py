from . import storage


def handler(event):
    bucket = event["bucket"]
    blob = event["blob"]

    client = storage.storage.get_instance()
    client.download_stream(bucket, blob)

    return "ok"
