import datetime, io, joblib, os, re, sys, zipfile

from time import time

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
    x = event['input']
    bucket = event['bucket']['name']
    bucket_path = event['bucket']['path']
    dataset_key = event['dataset']['key']
    model_key = event['model']['key']

    dataset_path = f'{bucket_path}/{dataset_key}'
    model_path = f'{bucket_path}/{model_key}'

    dataset_local_path = '/tmp/' + dataset_key
    model_local_path = '/tmp/' + model_key

    download_dataset_begin = datetime.datetime.now()
    client.download(bucket, dataset_path, dataset_local_path)
    download_dataset_end = datetime.datetime.now()

    download_model_begin = datetime.datetime.now()
    client.download(bucket, model_path, model_local_path)
    download_model_end = datetime.datetime.now()

    df = pd.read_csv(dataset_local_path)

    process_begin = datetime.datetime.now()
    df_input = pd.DataFrame()
    df_input['x'] = [x]
    df_input['x'] = df_input['x'].apply(cleanup)

    df['train'] = df['Text'].apply(cleanup)
    tfidf_vect = TfidfVectorizer(min_df=100).fit(df['train'])
    X = tfidf_vect.transform(df_input['x'])

    model = joblib.load(model_local_path)
    y = model.predict(X)
    process_end = datetime.datetime.now()

    download_dataset_time = (download_dataset_end - download_dataset_begin) / datetime.timedelta(microseconds=1)
    download_model_time = (download_model_end - download_model_begin) / datetime.timedelta(microseconds=1)
    process_time = (process_end - process_begin) / datetime.timedelta(microseconds=1)

    return {
        'result': 0,
        'measurement': {
            'download_dataset_time': download_dataset_time,
            'download_model_time': download_model_time,
            'process_time': process_time
        }
    }
