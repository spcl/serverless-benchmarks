import datetime, io
from sklearn.feature_extraction.text import TfidfVectorizer

from . import misc
from . import storage
client = storage.storage.get_instance()


def handler(event):
    bucket = event['bucket']['name']

    list_begin = datetime.datetime.now()
    objs = client.list_objects(bucket, misc.object_path('extractors_output', ''))
    list_end = datetime.datetime.now()

    result = []
    preprocess_begin = datetime.datetime.now()
    for obj in objs:
        body = str(client.get_object(bucket, obj))

        word = body.replace("'", '').split(',')
        result.extend(word)
    preprocess_end = datetime.datetime.now()

    # Cleanup the bucket between function iterations.
    delete_begin = datetime.datetime.now()
    for obj in objs:
        client.delete_object(bucket, obj)
    delete_end = datetime.datetime.now()

    process_begin = datetime.datetime.now()
    tfidf_vect = TfidfVectorizer().fit(result)
    feature = str(tfidf_vect.get_feature_names_out())
    feature = feature.lstrip('[').rstrip(']').replace(' ' , '')
    process_end = datetime.datetime.now()

    upload_begin = datetime.datetime.now()
    client.upload_stream(
        bucket,
        misc.object_path('reducer_output', 'feature'),
        io.BytesIO(feature.encode('utf-8')),
        True
    )
    upload_end = datetime.datetime.now()

    list_time = (list_end - list_begin) / datetime.timedelta(microseconds=1)
    preprocess_time = (preprocess_end - preprocess_begin) / datetime.timedelta(microseconds=1)
    delete_time = (delete_end - delete_begin) / datetime.timedelta(microseconds=1)
    process_time = (process_end - process_begin) / datetime.timedelta(microseconds=1)
    upload_time = (upload_end - upload_begin) / datetime.timedelta(microseconds=1)
    return {
        'result': 0,
        'measurement': {
            'list_time': list_time,
            'preprocess_time': preprocess_time,
            'delete_time': delete_time,
            'process_time': process_time,
            'upload_time': upload_time
        }
    }
