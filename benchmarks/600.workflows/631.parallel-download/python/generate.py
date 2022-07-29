def handler(event):
    count = int(event["count"])
    del event["count"]

    return {
        "buffer": count * [event]
    }