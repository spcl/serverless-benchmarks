import datetime, io, joblib, json, os, re, sys, zipfile

from time import time

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

from importlib.metadata import version

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

cleanup_re = re.compile('[^a-z]+')
def cleanup(sentence):
    sentence = sentence.lower()
    sentence = cleanup_re.sub(' ', sentence).strip()
    return sentence

def handler(event):
    bucket = event['bucket']['name']
    bucket_path = event['bucket']['path']
    dataset_key = event['dataset']['key']
    model_key = event['model']['key']

    dataset_path = f'{bucket_path}/{dataset_key}'
    model_path = f'{bucket_path}/{model_key}'

    model_local_path = '/tmp/' + model_key

    download_begin = datetime.datetime.now()
    dataset = client.get_object(bucket, dataset_path)
    download_end = datetime.datetime.now()

    df = pd.read_csv(io.BytesIO(dataset))

    process_begin = datetime.datetime.now()
    df['train'] = df['Text'].apply(cleanup)

    tfidf_vector = TfidfVectorizer(min_df=100).fit(df['train'])

    train = tfidf_vector.transform(df['train'])

    model = LogisticRegression()
    model.fit(train, df['Score'])
    process_end = datetime.datetime.now()

    joblib.dump(model, model_local_path)

    upload_begin = datetime.datetime.now()
    client.upload(bucket, model_path, model_local_path, True)
    upload_end = datetime.datetime.now()

    prediction_input = {'dataset': {}, 'model': {}, 'bucket': {}}
    prediction_input['input'] = event['input']
    prediction_input['bucket']['name'] = bucket
    prediction_input['bucket']['path'] = bucket_path
    prediction_input['dataset']['key'] = dataset_key
    prediction_input['model']['key'] = model_key
    prediction_input['parent_execution_id'] = event['request-id']

    queue_begin = datetime.datetime.now()
    queue_client = queue.queue(
        misc.function_name(
            fname='prediction',
            language='python',
            version='3.9',
            trigger='queue'
        )
    )
    queue_client.send_message(json.dumps(prediction_input))
    queue_end = datetime.datetime.now()

    download_time = (download_end - download_begin) / datetime.timedelta(microseconds=1)
    process_time = (process_end - process_begin) / datetime.timedelta(microseconds=1)
    upload_time = (upload_end - upload_begin) / datetime.timedelta(microseconds=1)
    queue_time = (queue_end - queue_begin) / datetime.timedelta(microseconds=1)
    return {
        'result': prediction_input,
        'fns_triggered': 1,
        'measurement': {
            'download_time': download_time,
            'process_time': process_time,
            'upload_time': upload_time,
            'queue_time': queue_time
        }
    }
