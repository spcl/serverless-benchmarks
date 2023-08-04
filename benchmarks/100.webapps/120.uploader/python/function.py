import datetime
import os
import uuid
import urllib.request
from jsonschema import validate

from . import storage
client = storage.storage.get_instance()

def handler(event):
  
    scheme = {
        "type": "object",
        "required": ["bucket", "object"],
        "properties": {
            "bucket": {
                "type": "object",
                "required": ["output"]
            },
            "object": {
                "type": "object",
                "required": ["url"]
            }
        }
    }

    try:
        validate(event, schema=scheme)
    except:
        return { 'status': 'failure', 'result': 'Some value(s) is/are not found in JSON data or of incorrect type' }
    
    output_bucket = event['bucket']['output']
    url = event['object']['url']
    name = os.path.basename(url)
    download_path = f'/tmp/{name}'

    process_begin = datetime.datetime.now()
    urllib.request.urlretrieve(url, filename=download_path)
    size = os.path.getsize(download_path)
    process_end = datetime.datetime.now()

    upload_begin = datetime.datetime.now()
    key_name = client.upload(output_bucket, name, download_path)
    upload_end = datetime.datetime.now()

    process_time = (process_end - process_begin) / datetime.timedelta(microseconds=1)
    upload_time = (upload_end - upload_begin) / datetime.timedelta(microseconds=1)
    return {
            'status': 'success',
            'result': 'Returned with no error',
            'measurement': {
                'bucket': output_bucket,
                'url': url,
                'key': key_name,
                'download_time': 0,
                'download_size': 0,
                'upload_time': upload_time,
                'upload_size': size,
                'compute_time': process_time
            }
    }
