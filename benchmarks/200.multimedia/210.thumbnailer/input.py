# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
import glob
import os
import tempfile

from PIL import Image

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

    for file in glob.glob(os.path.join(data_dir, '*.jpg')):
        img = os.path.relpath(file, data_dir)
        upload_func(0, img, file)

    #TODO: multiple datasets
    input_config = {'object': {}, 'bucket': {}}
    input_config["object"]["key"] = "6_astronomy-desktop-wallpaper-evening-1624438.jpg"
    input_config['object']['width'] = 200
    input_config['object']['height'] = 200
    input_config['bucket']['bucket'] = benchmarks_bucket
    input_config['bucket']['input'] = input_paths[0]
    input_config['bucket']['output'] = output_paths[0]
    return input_config

def validate_output(data_dir: str | None, input_config: dict, output: dict, language: str, storage = None) -> str | None:

    result = output.get('result', {})
    key = result.get('key', '')

    if not isinstance(key, str) or len(key) == 0:
        return f"Output key is missing or invalid (type={type(key).__name__}, value='{key}')"

    if storage is None:
        return None

    bucket = input_config.get('bucket', {}).get('bucket', '')
    max_width = input_config.get('object', {}).get('width', 0)
    max_height = input_config.get('object', {}).get('height', 0)

    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
        tmp_path = f.name
    try:
        storage.download(bucket, key, tmp_path)
        file_size = os.path.getsize(tmp_path)
        if file_size == 0:
            return f"Downloaded thumbnail from storage is empty (bucket='{bucket}', key='{key}')"

        try:
            with Image.open(tmp_path) as img:
                w, h = img.size
                if w <= 0 or h <= 0:
                    return f"Thumbnail has invalid dimensions: width={w}, height={h}"
                if w > max_width:
                    return f"Thumbnail width {w} exceeds maximum {max_width}"
                if h > max_height:
                    return f"Thumbnail height {h} exceeds maximum {max_height}"
                return None
        except Exception as e:
            return f"Failed to open or validate thumbnail image: {str(e)}"
    finally:
        os.unlink(tmp_path)
