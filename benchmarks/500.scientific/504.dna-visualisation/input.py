# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
import glob, os

def buckets_count():
    return (1, 1)

def generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_func, nosql_func):

    for file in glob.glob(os.path.join(data_dir, '*.fasta')):
        data = os.path.relpath(file, data_dir)
        upload_func(0, data, file)
    input_config = {'object': {}, 'bucket': {}}
    input_config['object']['key'] = data
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
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        tmp_path = f.name
    try:
        storage.download(bucket, key, tmp_path)
        return os.path.getsize(tmp_path) > 0
    finally:
        os.unlink(tmp_path)
