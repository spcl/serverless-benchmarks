import datetime, io, json
# using https://squiggle.readthedocs.io/en/latest/
from squiggle import transform

from . import storage
client = storage.storage.get_instance()

def handler(event):

    input_bucket = event.get('bucket').get('input')
    output_bucket = event.get('bucket').get('output')
    key = event.get('object').get('key')
    download_path = '/tmp/{}'.format(key)

    download_begin = datetime.datetime.now()
    client.download(input_bucket, key, download_path)
    download_stop = datetime.datetime.now()
    data = open(download_path, "r").read()

    process_begin = datetime.datetime.now()
    result = transform(data)
    process_end = datetime.datetime.now()

    upload_begin = datetime.datetime.now()
    buf = io.BytesIO(json.dumps(result).encode())
    buf.seek(0)
    key_name = client.upload_stream(output_bucket, key, buf)
    upload_stop = datetime.datetime.now()
    buf.close()

    download_time = (download_stop - download_begin) / datetime.timedelta(microseconds=1)
    process_time = (process_end - process_begin) / datetime.timedelta(microseconds=1)

    return {
            'result': {
                'bucket': output_bucket,
                'key': key_name
            },
            'measurement': {
                'download_time': download_time,
                'compute_time': process_time
            }
    }
