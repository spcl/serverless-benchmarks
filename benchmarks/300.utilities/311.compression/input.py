# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
import os
import tempfile
import zipfile


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

    input_config = {'object': {}, 'bucket': {}}
    input_config["object"]["key"] = "acmart-master"
    input_config['bucket']['bucket'] = benchmarks_bucket
    input_config['bucket']['input'] = input_paths[0]
    input_config['bucket']['output'] = output_paths[0]
    return input_config

def validate_output(input_config: dict, output: dict, language: str, storage = None) -> str | None:

    result = output.get('output', {})
    key = result.get('key', '')

    if not isinstance(key, str):
        return f"Output key is not a string (type={type(key).__name__})"
    if not key.endswith('.zip'):
        return f"Output key '{key}' does not end with .zip extension"

    if storage is None:
        return None

    bucket = input_config.get('bucket', {}).get('bucket', '')
    archive_key = input_config.get('object', {}).get('key', '')
    input_prefix = input_config.get('bucket', {}).get('input', '')

    # Get local data directory to compare with ZIP contents
    try:
        from sebs.utils import get_project_root
        data_dir = get_project_root() / 'benchmarks-data' / '300.utilities' / '311.compression' / archive_key
        if not data_dir.exists():
            return f"Local data directory not found: {data_dir}"

        # Collect expected files from local directory
        expected_files = set()
        for root, dirs, files in os.walk(data_dir):
            for file in files:
                # Path relative to archive_key directory
                rel_path = os.path.relpath(os.path.join(root, file), data_dir)
                expected_files.add(rel_path)

        if len(expected_files) == 0:
            return f"No files found in local data directory: {data_dir}"

    except Exception as e:
        return f"Error accessing local data directory: {str(e)}"

    # ZIP files are created with S3 prefix included in paths
    # e.g., "311.compression-0-input/acmart-master/README"
    zip_prefix = f"{input_prefix}/{archive_key}/"

    with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as f:
        tmp_path = f.name

    try:
        storage.download(bucket, key, tmp_path)
        file_size = os.path.getsize(tmp_path)
        if file_size == 0:
            return f"Downloaded ZIP archive is empty (bucket='{bucket}', key='{key}')"

        try:
            with zipfile.ZipFile(tmp_path, 'r') as zf:
                raw_zip_names = zf.namelist()
        except zipfile.BadZipFile:
            return f"Downloaded file is not a valid ZIP archive (bucket='{bucket}', key='{key}')"

        if len(raw_zip_names) == 0:
            return f"ZIP archive contains no files (bucket='{bucket}', key='{key}')"

        # Strip the S3 input prefix from ZIP paths to get relative paths
        # ZIP contains: "311.compression-0-input/acmart-master/README"
        # We need: "README"
        zip_files = set()
        for name in raw_zip_names:
            if name.startswith(zip_prefix):
                # Remove prefix and add to set (skip directory entries)
                rel_path = name[len(zip_prefix):]
                if rel_path and not rel_path.endswith('/'):
                    zip_files.add(rel_path)

        if len(zip_files) == 0:
            return f"ZIP archive contains no files with expected prefix '{zip_prefix}' (found {len(raw_zip_names)} entries)"

        # Compare: all expected files should be in the ZIP
        missing_files = expected_files - zip_files
        if missing_files:
            return f"ZIP archive is missing {len(missing_files)} expected files: {list(missing_files)[:5]}"

        # Also check for extra files (not critical, but informative)
        extra_files = zip_files - expected_files
        if extra_files:
            return f"ZIP archive contains {len(extra_files)} unexpected files: {list(extra_files)[:5]}"

        return None

    except Exception as e:
        return f"Error validating ZIP archive: {str(e)}"
    finally:
        os.unlink(tmp_path)
