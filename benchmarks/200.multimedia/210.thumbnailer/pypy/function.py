import datetime
import io
import os
import sys
import uuid
from urllib.parse import unquote_plus
from PIL import Image

from . import storage
client = storage.storage.get_instance()

# Disk-based solution
#def resize_image(image_path, resized_path, w, h):
#    with Image.open(image_path) as image:
#        image.thumbnail((w,h))
#        image.save(resized_path)

# Memory-based solution
def resize_image(image_bytes, w, h):
    with Image.open(io.BytesIO(image_bytes)) as image:
        image.thumbnail((w,h))
        out = io.BytesIO()
        image.save(out, format='jpeg')
        # necessary to rewind to the beginning of the buffer
        out.seek(0)
        return out

def handler(event):
  
    bucket = event.get('bucket').get('bucket')
    input_prefix = event.get('bucket').get('input')
    output_prefix = event.get('bucket').get('output')
    key = unquote_plus(event.get('object').get('key'))
    width = event.get('object').get('width')
    height = event.get('object').get('height')
    # UUID to handle multiple calls
    #download_path = '/tmp/{}-{}'.format(uuid.uuid4(), key)
    #upload_path = '/tmp/resized-{}'.format(key)
    #client.download(input_bucket, key, download_path)
    #resize_image(download_path, upload_path, width, height)
    #client.upload(output_bucket, key, upload_path)
    download_begin = datetime.datetime.now()
    img = client.download_stream(bucket, os.path.join(input_prefix, key))
    download_end = datetime.datetime.now()

    process_begin = datetime.datetime.now()
    resized = resize_image(img, width, height)
    resized_size = resized.getbuffer().nbytes
    process_end = datetime.datetime.now()

    upload_begin = datetime.datetime.now()
    key_name = client.upload_stream(bucket, os.path.join(output_prefix, key), resized)
    upload_end = datetime.datetime.now()

    download_time = (download_end - download_begin) / datetime.timedelta(microseconds=1)
    upload_time = (upload_end - upload_begin) / datetime.timedelta(microseconds=1)
    process_time = (process_end - process_begin) / datetime.timedelta(microseconds=1)
    return {
            'result': {
                'bucket': bucket,
                'key': key_name
            },
            'measurement': {
                'download_time': download_time,
                'download_size': len(img),
                'upload_time': upload_time,
                'upload_size': resized_size,
                'compute_time': process_time
            }
    }
