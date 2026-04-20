# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
import glob
import os
import tempfile
import hashlib

def buckets_count():
    return (1, 1)

# MD5 checksums for video processing output (operation, duration) -> hash
# These checksums ensure ffmpeg produces deterministic output
expected_checksums = {
    ('watermark', 1): '87f3a1ef9d90f93fd24c19ad0209a913',
    ('watermark', 3): '98286aa95fdbd7501b2cf244027c0ca2',
    ('extract-gif', 2): '20c17009382df93f6fcbf7ba1c53def0'
}

'''
    Generate test, small and large workload for video processing.

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

    # Different operations for different sizes to test various video processing modes
    # Note: extract-gif can timeout on some configurations (long and heavy)
    size_configs = {
        'test': {'op': 'watermark', 'duration': 1},
        'small': {'op': 'watermark', 'duration': 3},
        'large': {'op': 'extract-gif', 'duration': 2},
    }

    config = size_configs.get(size, size_configs['test'])

    input_config = {'object': {}, 'bucket': {}}
    input_config['object']['key'] = "city.mp4"
    input_config['object']['op'] = config['op']
    input_config['object']['duration'] = config['duration']
    input_config['bucket']['bucket'] = benchmarks_bucket
    input_config['bucket']['input'] = input_paths[0]
    input_config['bucket']['output'] = output_paths[0]
    return input_config

def validate_output(input_config: dict, output: dict, language: str, storage = None) -> str | None:

    result = output.get('output', {})
    key = result.get('key', '')

    if not isinstance(key, str) or len(key) == 0:
        return f"Output key is missing or invalid (type={type(key).__name__}, value='{key}')"

    if storage is None:
        return None

    bucket = input_config.get('bucket', {}).get('bucket', '')
    op = input_config.get('object', {}).get('op', '')
    duration = input_config.get('object', {}).get('duration', 0)

    suffix = os.path.splitext(key)[1] or '.tmp'
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        tmp_path = f.name
    try:
        storage.download(bucket, key, tmp_path)
        file_size = os.path.getsize(tmp_path)
        if file_size == 0:
            return f"Downloaded video output from storage is empty (bucket='{bucket}', key='{key}')"

        # Check MD5 checksum if available for this operation
        checksum_key = (op, duration)
        if checksum_key not in expected_checksums:
            return f"Missing validation configuration for ({op}, {duration})!"

        with open(tmp_path, 'rb') as f:
            actual_md5 = hashlib.md5(f.read()).hexdigest()
        expected_md5 = expected_checksums[checksum_key]
        if actual_md5 != expected_md5:
            return f"MD5 checksum mismatch for op='{op}' duration={duration}: expected '{expected_md5}' but got '{actual_md5}'"

        return None
    finally:
        os.unlink(tmp_path)
