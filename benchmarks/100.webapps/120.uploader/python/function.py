
import datetime
import os
import uuid

import urllib.request

from . import storage
client = storage.storage.get_instance()


def handler(event):
  
    bucket = event.get('bucket').get('bucket')
    output_prefix = event.get('bucket').get('output')
    url = event.get('object').get('url')
    name = os.path.basename(url)
    download_path = '/tmp/{}'.format(name)

    process_begin = datetime.datetime.now()
    urllib.request.urlretrieve(url, filename=download_path)
    size = os.path.getsize(download_path)
    process_end = datetime.datetime.now()

    upload_begin = datetime.datetime.now()
    key_name = client.upload(bucket, os.path.join(output_prefix, name), download_path)
    upload_end = datetime.datetime.now()

    process_time = (process_end - process_begin) / datetime.timedelta(microseconds=1)
    upload_time = (upload_end - upload_begin) / datetime.timedelta(microseconds=1)
    return {
            'result': {
                'bucket': bucket,
                'url': url,
                'key': key_name
            },
            'measurement': {
                'download_time': 0,
                'download_size': 0,
                'upload_time': upload_time,
                'upload_size': size,
                'compute_time': process_time
            }
    }
