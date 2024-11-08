import datetime, io, json, os, uuid

from . import storage
client = storage.storage.get_instance()


def handler(event):
    text = event['input']

    count = 0
    word_for_this_reducer = ''

    process_begin = datetime.datetime.now()
    words = text.split('\n')[:-1]
    for word in words:
        splits = word.split(',')
        word_for_this_reducer = splits[0]
        count += int(splits[1])
    process_end = datetime.datetime.now()

    process_time = (process_end - process_start) / datetime.timedelta(microseconds=1)
    return {
        'result': { # Could also be written to S3
            word_for_this_reducer: count
        },
        'measurement': {
            'process_time': process_time
        },
        'fns_triggered': 0
    }
