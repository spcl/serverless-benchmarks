
from time import sleep

def handler(event):

    # start timing
    sleep(1)
    # sleep_time = event.get('sleep')
    # sleep(sleep_time)
    return { 'result': 1 }
