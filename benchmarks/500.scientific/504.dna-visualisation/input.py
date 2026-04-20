# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
import glob
import hashlib
import os
import tempfile

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

def validate_output(input_config: dict, output: dict, language: str, storage = None) -> str | None:

    result = output.get('result', {})
    key = result.get('key', '')

    if not isinstance(key, str):
        return f"Output key is not a string (type={type(key).__name__})"
    if len(key) == 0:
        return "Output key is empty"

    if storage is None:
        return None

    bucket = input_config.get('bucket', {}).get('bucket', '')

    # Expected MD5 checksum for DNA visualization output (deterministic)
    expected_checksum = 'b082a20fc9bf8f9bf67a3a265e2e6252'

    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        tmp_path = f.name
    try:
        storage.download(bucket, key, tmp_path)
        file_size = os.path.getsize(tmp_path)
        if file_size == 0:
            return f"Downloaded DNA visualization output is empty (bucket='{bucket}', key='{key}')"

        md5_hash = hashlib.md5()
        with open(tmp_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                md5_hash.update(chunk)
        actual_checksum = md5_hash.hexdigest()

        if actual_checksum != expected_checksum:
            return f"DNA visualization output checksum mismatch: expected '{expected_checksum}' but got '{actual_checksum}'"

        return None
    finally:
        os.unlink(tmp_path)
