import datetime, io, json
# using https://squiggle.readthedocs.io/en/latest/
from squiggle import transform
from jsonschema import validate

from . import storage
client = storage.storage.get_instance()

def handler(event):

    schema = {
        "type": "object",
        "required": ["bucket", "object"],
        "properties": {
            "bucket": {
                "type": "object",
                "required": ["input", "output"]
            },
            "object": {
                "type": "object",
                "required": ["key"]
            }
        }
    }
    
    try:
        validate(event, schema=schema)
    except:
        return { "status": "failure", 'result': 'Some value(s) is/are not found in JSON data or of incorrect type' }

    input_bucket = event['bucket']['input']
    output_bucket = event['bucket']['output']
    key = event['object']['key']
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
    # !? To include upload_time

    return {
            'status': 'success',
            'result': 'Returned with no error',
            'measurement': {
                'bucket': output_bucket,
                'key': key_name,
                'download_time': download_time,
                'compute_time': process_time
            }
    }
