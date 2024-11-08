import datetime, io, json, os, sys, uuid, zipfile

from . import misc
from . import queue
from . import storage
client = storage.storage.get_instance()

# Extract zipped pandas - which is otherwise too large for AWS/GCP.
if os.path.exists('function/pandas.zip'):
    zipfile.ZipFile('function/pandas.zip').extractall('/tmp/')
    sys.path.append(os.path.join(os.path.dirname(__file__), '/tmp/.python_packages/lib/site-packages/'))

if os.path.exists('./pandas.zip'):
    zipfile.ZipFile('./pandas.zip').extractall('/tmp/')
    sys.path.append(os.path.join(os.path.dirname(__file__), '/tmp/.python_packages/lib/site-packages/'))

import pandas as pd
import numpy as np


def handler(event):
    bucket = event['bucket']['name']

    if ('start_reducer' in event):
        reducer_input = {'bucket': {}}
        reducer_input['bucket']['name'] = bucket
        reducer_input['parent_execution_id'] = event['request-id']

        queue_begin = datetime.datetime.now()
        queue_client = queue.queue(
            misc.function_name(
                fname='reducer',
                language='python',
                version='3.9',
                trigger='queue'
            )
        )
        queue_client.send_message(json.dumps(reducer_input))
        queue_end = datetime.datetime.now()

        queue_time = (queue_end - queue_begin) / datetime.timedelta(microseconds=1)
        return {
            'result': reducer_input,
            'fns_triggered': 1,
            'measurement': {
                'queue_time': queue_time
            }
        }

    bucket_path = event['bucket']['path']
    dataset_key = event['object']['key']
    extractors = int(event['extractors'])

    dataset_path = f'{bucket_path}/{dataset_key}'
    dataset_local_path = '/tmp/' + dataset_key

    download_start = datetime.datetime.now()
    client.download(bucket, dataset_path, dataset_local_path)
    download_end = datetime.datetime.now()

    process_start = datetime.datetime.now()
    df = pd.read_csv(dataset_local_path)
    shards = np.array_split(df, extractors)
    process_end = datetime.datetime.now()

    # Prepare and send the output. Trigger 'extractors' and 'job_status'.
    extractor_bucket = misc.function_name(
        fname='extractor',
        language='python',
        version='3.9',
        trigger='storage'
    )

    upload_start = datetime.datetime.now()
    for shard in shards:
        key = f'shard-{uuid.uuid4()}'

        extractor_input = {'object': {}, 'output_bucket': {}}
        extractor_input['object']['key'] = key
        extractor_input['output_bucket']['name'] = bucket
        extractor_input['input'] = shard.to_json()
        extractor_input['parent_execution_id'] = event['request-id']
        client.upload_stream(
            extractor_bucket,
            key,
            io.BytesIO(json.dumps(extractor_input).encode('utf-8')),
            True
        )
    upload_end = datetime.datetime.now()

    job_status_input = {'output_bucket': {}}
    job_status_input['output_bucket']['name'] = bucket
    job_status_input['file_count'] = extractors
    job_status_input['parent_execution_id'] = event['request-id']
    queue_begin = datetime.datetime.now()
    queue_client = queue.queue(
        misc.function_name(
            fname='job_status',
            language='python',
            version='3.9',
            trigger='queue'
        )
    )
    queue_client.send_message(json.dumps(job_status_input))
    queue_end = datetime.datetime.now()

    download_time = (download_end - download_start) / datetime.timedelta(microseconds=1)
    process_time = (process_end - process_start) / datetime.timedelta(microseconds=1)
    upload_time = (upload_end - upload_start) / datetime.timedelta(microseconds=1)
    queue_time = (queue_end - queue_begin) / datetime.timedelta(microseconds=1)
    return {
        'result': 0,
        'fns_triggered': extractors + 1,
        'measurement': {
            'download_time': download_time,
            'process_time': process_time,
            'upload_time': upload_time,
            'queue_time': queue_time
        }
    }
