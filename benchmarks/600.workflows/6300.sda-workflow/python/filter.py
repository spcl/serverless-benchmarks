import os
import subprocess
import uuid

from . import storage

storage_client = storage.storage.get_instance()

def download_file(benchmark_bucket, bucket, basename, dest_dir):
    path = os.path.join(dest_dir, basename)
    storage_client.download(benchmark_bucket, bucket + '/' + basename, path)
    return path

def handler(event):
    benchmark_bucket = event["benchmark_bucket"]
    input_bucket = event["input_bucket"]
    input = event["input_file"]
    config = event["config_file"]
    TMP_DIR = os.path.join("/tmp",str(uuid.uuid4()))
    os.makedirs(TMP_DIR, exist_ok=True)
    input_path = download_file(benchmark_bucket, input_bucket, input, TMP_DIR)
    config_path = download_file(benchmark_bucket, input_bucket, config, TMP_DIR)
    result = subprocess.run([f"SettlementDelineationFilter", "-i", input_path, "-c", config_path],capture_output=True,text=True)
    return {"stdout": result.stdout, "stderr": result.stderr}