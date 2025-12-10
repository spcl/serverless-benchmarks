import os
import uuid
from pathlib import Path
from . import storage

storage_client = storage.storage.get_instance()

SHP_SUFFIX = [".shp", ".shx", ".dbf", ".prj"]
CONFIG_FILE_NAME = "sda-config.json"

def download_file(benchmark_bucket, path_in_bucket, dest_dir):
    path = Path(dest_dir) / Path(path_in_bucket).name
    storage_client.download(benchmark_bucket, path_in_bucket, path)
    return path

def download_file_bucket(benchmark_bucket, bucket, basename, dest_dir):
    return download_file(benchmark_bucket, bucket + '/' + basename, dest_dir)

def download_shp_file(benchmark_bucket, bucket ,shp_file, dest_dir):
    files = [Path(shp_file).with_suffix(suffix) for suffix in filter(lambda x: x is not ".shp",SHP_SUFFIX)]
    for f in files:
        download_file_bucket(benchmark_bucket, bucket, f.name, dest_dir)
    return download_file_bucket(benchmark_bucket, bucket, shp_file, dest_dir)

def load_config(benchmark_bucket, input_bucket,directory):
    return download_file_bucket(benchmark_bucket, input_bucket, CONFIG_FILE_NAME, directory)

def upload_shp_file(benchmark_bucket, bucket, shp_basename):
    shp_dir = Path(shp_basename).parent
    for f in shp_dir.iterdir():
        if Path(shp_basename).stem == Path(f).stem and any(f.name.endswith(suffix) for suffix in SHP_SUFFIX):
            full_path =  shp_dir / f.name
            storage_client.upload(benchmark_bucket, bucket + '/' + f.name, full_path,False)

def download_directory(benchmark_bucket, bucket, dest_dir):
    storage_client.download_directory(benchmark_bucket, bucket, dest_dir)

def create_tmp_dir():
    tmp_dir = os.path.join("/tmp",str(uuid.uuid4()))
    os.makedirs(tmp_dir, exist_ok=True)
    return tmp_dir