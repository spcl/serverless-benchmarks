import datetime, io, json, os, uuid

from . import misc
from . import storage
client = storage.storage.get_instance()


def handler(event):
    mappers = int(event['mappers'])

    # check that all files from the mappers are ready
    list_begin = datetime.datetime.now()
    objs = client.list_objects(
        misc.function_name(
            fname='sorter',
            language='python',
            version='3.9',
            trigger='storage'
        )
    )
    list_end = datetime.datetime.now()
    list_time = (list_end - list_begin) / datetime.timedelta(microseconds=1)

    if (len(objs) != mappers):
        return {
            'result': 0,
            'measurement': {
                'list_time': list_time
            }
        }

    # download everything and stick it together: ['bear,1', 'pear,3', 'pear,4']
    process_begin = datetime.datetime.now()
    word_list = []
    for obj in objs:
        words = client.get_object(fn_name, obj)
        words = json.loads(words)

        for k, v in words['counts'].items():
            word_list.append('{},{}'.format(k, str(v)))

    # sort
    word_list.sort()

    # everything which is the same goes into one file, e.g. all pears
    current = [word_list[0]]
    groups = []
    for i in range(0, len(word_list) - 1):
        if word_list[i].split(',')[0] == word_list[i + 1].split(',')[0]:
            current.append(word_list[i + 1])
        else:
            groups.append(current)
            current = [word_list[i + 1]]
    if (len(current)):
        groups.append(current)

    # flatten groups
    new_group = []
    for group in groups:
        flattened = ''
        for word in group:
            flattened += word + '\n'
        new_group.append(flattened)
    groups = new_group
    process_end = datetime.datetime.now()
    
    # publish to bucket
    upload_begin = datetime.datetime.now()
    fns_triggered = len(groups)
    for group in groups:
        word = group.split(',')[0]

        reducer_input = {
            'input': group,
            'parent_execution_id': event['request-id']
        }

        local_path = f'/tmp/{word}'
        with open(local_path, 'w') as f:
            f.write(json.dumps(reducer_input))

        fn_name = misc.function_name(
            fname='reducer',
            language='python',
            version='3.9',
            trigger='storage'
        )
        client.upload(fn_name, word, local_path)
    upload_end = datetime.datetime.now()

    process_time = (process_end - process_begin) / datetime.timedelta(microseconds=1)
    upload_time = (upload_end - upload_begin) / datetime.timedelta(microseconds=1)
    return {
        'result': 0,
        'fns_triggered': fns_triggered,
        'measurement': {
            'list_time': list_time,
            'process_time': process_time,
            'upload_time': upload_time
        }
    }
