import datetime, io, json, os

from . import misc
from . import storage
client = storage.storage.get_instance()


def handler(event):
    mappers = int(event['mappers'])
    text = event['text']

    # split by .
    sentences = text.split('.')

    # obtain length of list
    chunk_size = len(sentences) // mappers

    # split the list according to how many mappers are declared
    local_path = '/tmp/payload.json'
    for i in range(mappers):
        begin_range = i * chunk_size
        end_range = min((i + 1) * chunk_size, len(sentences))
        mapper_input = {
            'text': ' '.join(sentences[begin_range : end_range]),
            'mappers': mappers,
            'parent_execution_id': event['request-id']
        }
        with open(local_path, 'w') as f:
            f.write(json.dumps(mapper_input))

        # storage trigger code: for each mapper, upload to bucket
        bucket = misc.function_name(
            fname='mapper',
            language='python',
            version='3.9',
            trigger='storage'
        )
        client.upload(bucket, f'payload{i}.json', local_path, True)

    return {
        'result': 0,
        'fns_triggered': mappers,
        'measurement': {}
    }
