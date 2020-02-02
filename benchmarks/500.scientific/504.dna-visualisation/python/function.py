import datetime
# using https://squiggle.readthedocs.io/en/latest/
from squiggle import transform

from . import storage
client = storage.storage.get_instance()

def handler(event):

    input_bucket = event.get('bucket').get('input')
    key = event.get('object').get('key')
    download_path = '/tmp/{}'.format(key)

    download_begin = datetime.datetime.now()
    client.download(input_bucket, key, download_path)
    download_stop = datetime.datetime.now()

    data = open(download_path, "r").read()

    process_begin = datetime.datetime.now()
    result = transform(data)
    process_end = datetime.datetime.now()

    download_time = (download_stop - download_begin) / datetime.timedelta(microseconds=1)
    process_time = (process_end - process_begin) / datetime.timedelta(microseconds=1)

    return {
            'result': result,
            'measurement': {
                'download_time': download_time,
                'compute_time': process_time
            }
    }
