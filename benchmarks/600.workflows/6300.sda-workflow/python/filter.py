import os
import subprocess
import uuid

from . import storage

storage_client = storage.storage.get_instance()

def download_file(benchmark_bucket, bucket, basename, dest_dir):
    path = os.path.join(dest_dir, basename)
    storage_client.download(benchmark_bucket, bucket + '/' + basename, path)
    return path

SHP_SUFFIX = [".shp", ".shx", ".dbf", ".prj"]

def upload_shp_file(benchmark_bucket, bucket, shp_dir):
    for f in os.listdir(shp_dir):
        if any(f.endswith(suffix) for suffix in SHP_SUFFIX):
            full_path =  os.path.join(shp_dir, f)
            storage_client.upload(benchmark_bucket, bucket + '/' + f, full_path)
    
def handler(event):
    benchmark_bucket = event["benchmark_bucket"]
    input_bucket = event["input_bucket"]
    output_bucket = event["output_bucket"]
    input = event["input_file"]
    config = event["config_file"]
    TMP_DIR = os.path.join("/tmp",str(uuid.uuid4()))
    os.makedirs(TMP_DIR, exist_ok=True)
    input_path = download_file(benchmark_bucket, input_bucket, input, TMP_DIR)
    config_path = download_file(benchmark_bucket, input_bucket, config, TMP_DIR)
    # Store workflow data in /tmp due to read only filesystem restriction
    result = subprocess.run([f"SettlementDelineationFilter", "-i", input_path, "-c", config_path, "-o", TMP_DIR],capture_output=True,text=True)
    upload_shp_file(benchmark_bucket, output_bucket, TMP_DIR)
    return {"stdout": result.stdout, "stderr": result.stderr}