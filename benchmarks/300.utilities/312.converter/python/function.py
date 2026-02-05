import openpyxl
import json
import datetime
import os
import io
from urllib.parse import unquote_plus

from . import storage
client = storage.storage.get_instance()

def convertJson(json_input):
    if isinstance(json_input, str):
        data = json.loads(json_input)
    else:
        data = json_input

    wb = openpyxl.Workbook()
    ws = wb.active

    ordered_keys = [f'a{i}' for i in range(1, 21)]

    for entry in data:
        row_values = [entry[key] for key in ordered_keys]
        ws.append(row_values)

    outputStream = io.BytesIO()
    wb.save(outputStream)
    outputStream.seek(0)
    return outputStream

def handler(event):
    bucket = event.get('bucket').get('bucket')
    input_prefix = event.get('bucket').get('input')
    output_prefix = event.get('bucket').get('output')

    key = unquote_plus(event.get('object').get('key'))
    download_begin = datetime.datetime.now()
    jsonMemView = client.download_stream(bucket, os.path.join(input_prefix, key))
    download_end = datetime.datetime.now()
    jsonObj = json.loads(jsonMemView.tobytes())
    process_begin = datetime.datetime.now()
    xlsxFileBytes = convertJson(jsonObj)
    xlsxSize = xlsxFileBytes.getbuffer().nbytes
    process_end = datetime.datetime.now()
    
    upload_begin = datetime.datetime.now()
    outputFilename = 'output.xlsx'
    key_name = client.upload_stream(bucket, os.path.join(output_prefix, outputFilename), xlsxFileBytes)
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
            'download_size': len(jsonMemView),
            'upload_time': upload_time,
            'upload_size': xlsxSize,
            'compute_time': process_time
        }
    }