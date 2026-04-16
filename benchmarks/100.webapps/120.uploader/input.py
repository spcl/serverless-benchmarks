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
    'large':  'https://download.pytorch.org/models/resnet50-19c8e357.pth'
}

# MD5 checksums for stable reference objects.
# These are computed from the objects at the URLs above and must be updated
# if the remote files change.
expected_checksums = {
    'test': '91799b8ca818598fc5b8790f3b338150',
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

def validate_output(input_config: dict, output: dict, storage=None) -> bool:
    result = output.get('result', {})
    key = result.get('key', '')
    url = input_config.get('object', {}).get('url', '')
    size = input_config.get('object', {}).get('size', '')
    if not (isinstance(key, str) and len(key) > 0 and result.get('url') == url):
        return False
    if storage is None:
        return True
    bucket = input_config.get('bucket', {}).get('bucket', '')
    expected_name = os.path.basename(url)
    if not key.endswith(expected_name):
        return False
    with tempfile.NamedTemporaryFile(delete=False) as f:
        tmp_path = f.name
    try:
        storage.download(bucket, key, tmp_path)
        if os.path.getsize(tmp_path) == 0:
            return False
        if size in expected_checksums:
            with open(tmp_path, 'rb') as f:
                actual_md5 = hashlib.md5(f.read()).hexdigest()
            if actual_md5 != expected_checksums[size]:
                return False
    finally:
        os.unlink(tmp_path)
    return True
