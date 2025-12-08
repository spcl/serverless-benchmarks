import os
import uuid
from pathlib import Path
from . import storage

storage_client = storage.storage.get_instance()

SHP_SUFFIX = [".shp", ".shx", ".dbf", ".prj"]

def download_file(benchmark_bucket, path_in_bucket, dest_dir):
    path = Path(dest_dir) / Path(path_in_bucket).name
    storage_client.download(benchmark_bucket, path_in_bucket, path)
    return path

def download_file_bucket(benchmark_bucket, bucket, basename, dest_dir):
    return download_file(benchmark_bucket, bucket + '/' + basename, dest_dir)

def download_shp_file(benchmark_bucket, files, dest_dir):
    path = None
    for filename in files:
        path = download_file(benchmark_bucket, filename, dest_dir)
    return path.with_suffix(".shp")

def store_config(json_string,directory):
    config_path = Path(directory) / "config.json"
    with open(config_path,'w') as f:
        f.write(json_string)
    return config_path

def upload_shp_file(benchmark_bucket, bucket, shp_basename):
    shp_dir = Path(shp_basename).parent
    for f in shp_dir.iterdir():
        if Path(shp_basename).stem == Path(f).stem and any(f.name.endswith(suffix) for suffix in SHP_SUFFIX):
            full_path =  shp_dir / f.name
            yield storage_client.upload(benchmark_bucket, bucket + '/' + f.name, full_path,False)

def create_tmp_dir():
    tmp_dir = os.path.join("/tmp",str(uuid.uuid4()))
    os.makedirs(tmp_dir, exist_ok=True)
    return tmp_dir