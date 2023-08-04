import datetime
import io
import os
import sys
import uuid
from urllib.parse import unquote_plus
from PIL import Image
from jsonschema import validate

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
  
    scheme = {
        "type": "object",
        "required": ["bucket", "object"],
        "properties": {
            "bucket": {
                "type": "object",
                "required": ["output", "input"]
            },
            "object": {
                "type": "object",
                "required": ["key", "width", "height"]
            }
        }
    }

    try:
        validate(event, schema=scheme)
    except:
        return { 'status': 'failure', 'result': 'Some value(s) is/are not found in JSON data or of incorrect type' }
    
    input_bucket = event['bucket']['input']
    output_bucket = event['bucket']['output']
    key = unquote_plus(event['object']['key'])
    width = event['object']['width']
    height = event['object']['height']
    # UUID to handle multiple calls
    #download_path = '/tmp/{}-{}'.format(uuid.uuid4(), key)
    #upload_path = '/tmp/resized-{}'.format(key)
    #client.download(input_bucket, key, download_path)
    #resize_image(download_path, upload_path, width, height)
    #client.upload(output_bucket, key, upload_path)
    download_begin = datetime.datetime.now()
    img = client.download_stream(input_bucket, key)
    download_end = datetime.datetime.now()

    process_begin = datetime.datetime.now()
    resized = resize_image(img, width, height)
    resized_size = resized.getbuffer().nbytes
    process_end = datetime.datetime.now()

    upload_begin = datetime.datetime.now()
    key_name = client.upload_stream(output_bucket, key, resized)
    upload_end = datetime.datetime.now()

    download_time = (download_end - download_begin) / datetime.timedelta(microseconds=1)
    upload_time = (upload_end - upload_begin) / datetime.timedelta(microseconds=1)
    process_time = (process_end - process_begin) / datetime.timedelta(microseconds=1)
    return {
            'status': 'success',
            'result': 'Returned with no error',
            'measurement': {
                'bucket': output_bucket,
                'key': key_name,    
                'download_time': download_time,
                'download_size': len(img),
                'upload_time': upload_time,
                'upload_size': resized_size,
                'compute_time': process_time
            }
    }
