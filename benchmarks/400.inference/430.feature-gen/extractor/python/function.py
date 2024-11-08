import datetime, io, json, os, re, sys, uuid, zipfile

from . import misc
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


cleanup_re = re.compile('[^a-z]+')

def cleanup(sentence):
    sentence = sentence.lower()
    sentence = cleanup_re.sub(' ', sentence).strip()
    return sentence

def handler(event):
    output_bucket = event['output_bucket']['name']
    dataset_key = event['object']['key']

    # Cleanup the bucket between function iterations.
    input_bucket = misc.function_name(
        fname='extractor',
        language='python',
        version='3.9',
        trigger='storage'
    )
    delete_begin = datetime.datetime.now()
    client.delete_object(input_bucket, dataset_key)
    delete_end = datetime.datetime.now()

    # Do the work.
    process_begin = datetime.datetime.now()
    df = pd.read_json(event['input'])

    df['Text'] = df['Text'].apply(cleanup)
    text = df['Text'].tolist()
    result = set()
    for item in text:
        result.update(item.split())

    feature = str(list(result))
    feature = feature.lstrip('[').rstrip(']').replace(' ', '')
    process_end = datetime.datetime.now()

    key = misc.object_path('extractors_output', dataset_key.split('.')[0] + '.txt')
    upload_start = datetime.datetime.now()
    client.upload_stream(
        output_bucket,
        key,
        io.BytesIO(feature.encode('utf-8')),
        True
    )
    upload_end = datetime.datetime.now()

    delete_time = (delete_end - delete_begin) / datetime.timedelta(microseconds=1)
    process_time = (process_end - process_begin) / datetime.timedelta(microseconds=1)
    upload_time = (upload_end - upload_start) / datetime.timedelta(microseconds=1)
    return {
        'result': 0,
        'measurement': {
            'delete_time': delete_time,
            'process_time': process_time,
            'upload_time': upload_time
        }
    }
