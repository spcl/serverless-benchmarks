import datetime, io, json, os, uuid

from . import misc
from . import storage
client = storage.storage.get_instance()


def handler(event):
    text = event['text']

    # split by space
    process_begin = datetime.datetime.now()
    words = text.split(' ')

    # count for every word
    counts = {}
    for word in words:
        if word not in counts:
            counts[word] = 1
        else:
            counts[word] += 1
    counts = dict(sorted(counts.items()))
    process_end = datetime.datetime.now()

    sorter_input = {
        'counts': counts,
        'mappers': event['mappers'],
        'parent_execution_id': event['request-id']
    }

    file_name = f'payload{str(uuid.uuid4())}.json'
    file_path = f'/tmp/{file_name}'
    with open(file_path, 'w') as f:
        f.write(json.dumps(sorter_input))

    bucket = misc.function_name(
                fname='sorter',
                language='python',
                version='3.9',
                trigger='storage'
            )
    upload_begin = datetime.datetime.now()
    client.upload(bucket, file_name, file_path)
    upload_end = datetime.datetime.now()

    process_time = (process_end - process_begin) / datetime.timedelta(microseconds=1)
    upload_time = (upload_end - upload_begin) / datetime.timedelta(microseconds=1)
    return {
        'result': counts,
        'fns_triggered': 1,
        'measurement': {
            'process_time': process_time,
            'upload_time': upload_time
        }
    }
