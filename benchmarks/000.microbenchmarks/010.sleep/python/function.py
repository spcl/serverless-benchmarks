
from time import sleep

def handler(event):

    # start timing
    sleep_time = event.get('sleep', default=None)
    if sleep_time is None:
        return { "status": "failure", "result": "Error: Key 'sleep' not found on input data." }
    elif not isinstance(sleep_time, (int, float)):
        return { "status": "failure", "result": "Error: Unexpected type for 'sleep' (expected int or float)"}
    
    sleep(sleep_time)
    return { "status": "success", "result": "Returned with no error", "measurement": sleep_time }
