import time

def handler(event):
    time.sleep(event['sleep'])


    return "ok"
