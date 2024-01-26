def handler(event):
    count = int(event["count"])
    sleep = int(event["sleep"])
    buffer = count * [sleep]


    return {
        "buffer": buffer
    }
