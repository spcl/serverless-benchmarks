# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
import hashlib
import os
import tempfile

url_generators = {
    # source: mlperf fake_imagenet.sh. 230 kB
    'test' : 'https://upload.wikimedia.org/wikipedia/commons/thumb/e/e7/Jammlich_crop.jpg/800px-Jammlich_crop.jpg',
    # video: HPX source code, 6.7 MB
    'small': 'https://github.com/STEllAR-GROUP/hpx/archive/refs/tags/1.4.0.zip',
    # resnet model from pytorch. 98M
    'large': 'https://download.pytorch.org/models/resnet50-19c8e357.pth'
}

# MD5 checksums for stable reference objects.
# These are computed from the objects at the URLs above and must be updated
# if the remote files change.
expected_checksums = {
    'test': '91799b8ca818598fc5b8790f3b338150',
    'small': 'baf7ea99128aa3e5c2d0c8b8f61cce1b',
    'large': '9e9c86b324d80e65229fab49b8d9a8e8'
}

def buckets_count():
    return (0, 1)

def generate_input(data_dir, size, benchmarks_bucket, input_buckets, output_buckets, upload_func, nosql_func):
    input_config = {'object': {}, 'bucket': {}}
    input_config['object']['url'] = url_generators[size]
    input_config['object']['size'] = size
    input_config['bucket']['bucket'] = benchmarks_bucket
    input_config['bucket']['output'] = output_buckets[0]
    return input_config

def validate_output(data_dir: str | None, input_config: dict, output: dict, language: str, storage = None) -> str | None:

    result = output.get('result', {})
    key = result.get('key', '')
    url = input_config.get('object', {}).get('url', '')
    size = input_config.get('object', {}).get('size', '')

    if not isinstance(key, str) or len(key) == 0:
        return f"Output key is missing or invalid (type={type(key).__name__}, value='{key}')"

    if result.get('url') != url:
        return f"Output URL mismatch: expected '{url}' but got '{result.get('url')}'"

    if storage is None:
        return None

    bucket = input_config.get('bucket', {}).get('bucket', '')
    expected_name = os.path.basename(url)
    # Storage client adds unique hash: filename.{hash}.ext
    # Check that the key contains the base filename and has the same extension
    expected_base, expected_ext = os.path.splitext(expected_name)
    key_base = os.path.basename(key)
    if not (expected_base in key_base and key_base.endswith(expected_ext)):
        return f"Storage key '{key_base}' does not match expected pattern (base='{expected_base}', ext='{expected_ext}')"

    with tempfile.NamedTemporaryFile(delete=False) as f:
        tmp_path = f.name
    try:
        storage.download(bucket, key, tmp_path)
        file_size = os.path.getsize(tmp_path)
        if file_size == 0:
            return f"Downloaded file from storage is empty (bucket='{bucket}', key='{key}')"

        with open(tmp_path, 'rb') as f:
            actual_md5 = hashlib.md5(f.read()).hexdigest()
        if actual_md5 != expected_checksums[size]:
            return f"MD5 checksum mismatch for size '{size}': expected '{expected_checksums[size]}' but got '{actual_md5}'"
    finally:
        os.unlink(tmp_path)
    return None
