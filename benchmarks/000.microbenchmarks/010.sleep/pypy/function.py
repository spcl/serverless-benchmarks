
from time import sleep

def handler(event):

    # start timing
    sleep_time = event.get('sleep')
    sleep(sleep_time)
    return { 'result': sleep_time }
