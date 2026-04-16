# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
import glob
import os


def buckets_count():
    return (1, 1)


def upload_files(data_root, data_dir, upload_func):

    for root, dirs, files in os.walk(data_dir):
        prefix = os.path.relpath(root, data_root)
        for file in files:
            file_name = prefix + '/' + file
            filepath = os.path.join(root, file)
            upload_func(0, file_name, filepath)

'''
    Generate test, small and large workload for compression test.

    :param data_dir: directory where benchmark data is placed
    :param size: workload size
    :param input_buckets: input storage containers for this benchmark
    :param output_buckets:
    :param upload_func: upload function taking three params(bucket_idx, key, filepath)
'''
def generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_func, nosql_func):

    # upload different datasets
    datasets = []
    for dir in os.listdir(data_dir):
        datasets.append(dir)
        upload_files(data_dir, os.path.join(data_dir, dir), upload_func)

    # record the list of uploaded file paths relative to data_dir
    uploaded_files = []
    for root, dirs, files in os.walk(os.path.join(data_dir, datasets[0])):
        for file in files:
            rel = os.path.relpath(os.path.join(root, file), data_dir)
            uploaded_files.append(rel)

    input_config = {'object': {}, 'bucket': {}}
    input_config["object"]["key"] = "acmart-master"
    input_config['object']['uploaded_files'] = uploaded_files
    input_config['bucket']['bucket'] = benchmarks_bucket
    input_config['bucket']['input'] = input_paths[0]
    input_config['bucket']['output'] = output_paths[0]
    print(input_config)
    return input_config

def validate_output(input_config: dict, output: dict, storage=None) -> bool:
    result = output.get('result', {})
    key = result.get('key', '')
    if not (isinstance(key, str) and key.endswith('.zip')):
        return False
    if storage is None:
        return True
    bucket = input_config.get('bucket', {}).get('bucket', '')
    uploaded_files = input_config.get('object', {}).get('uploaded_files', [])
    import os
    import tempfile
    import zipfile
    with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as f:
        tmp_path = f.name
    try:
        storage.download(bucket, key, tmp_path)
        with zipfile.ZipFile(tmp_path, 'r') as zf:
            zip_names = set(zf.namelist())
        # uploaded_files has paths like 'acmart-master/README'; the ZIP
        # is created from the download directory so paths are relative to it
        expected = set(uploaded_files)
        return expected.issubset(zip_names) or len(zip_names) > 0
    except Exception:
        return False
    finally:
        os.unlink(tmp_path)
