# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
import glob, os

def buckets_count():
    return (1, 1)

'''
    Generate test, small and large workload for thumbnailer.

    :param data_dir: directory where benchmark data is placed
    :param size: workload size
    :param input_buckets: input storage containers for this benchmark
    :param output_buckets:
    :param upload_func: upload function taking three params(bucket_idx, key, filepath)
'''
def generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_func, nosql_func):
    for file in glob.glob(os.path.join(data_dir, '*.mp4')):
        img = os.path.relpath(file, data_dir)
        upload_func(0, img, file)
    #TODO: multiple datasets
    input_config = {'object': {}, 'bucket': {}}
    input_config['object']['key'] = img
    input_config['object']['op'] = 'watermark'
    input_config['object']['duration'] = 1
    input_config['bucket']['bucket'] = benchmarks_bucket
    input_config['bucket']['input'] = input_paths[0]
    input_config['bucket']['output'] = output_paths[0]
    return input_config

def validate_output(input_config: dict, output: dict, storage=None) -> bool:
    result = output.get('result', {})
    key = result.get('key', '')
    if not (isinstance(key, str) and len(key) > 0):
        return False
    if storage is None:
        return True
    bucket = input_config.get('bucket', {}).get('bucket', '')
    import os, tempfile
    suffix = os.path.splitext(key)[1] or '.tmp'
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        tmp_path = f.name
    try:
        storage.download(bucket, key, tmp_path)
        return os.path.getsize(tmp_path) > 0
    finally:
        os.unlink(tmp_path)
