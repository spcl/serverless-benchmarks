import subprocess
from .SDAHelper import *
    
def handler(event):
    benchmark_bucket = event["benchmark_bucket"]
    input = event["filtered_files"]
    config = event["config_file"]
    TMP_DIR = os.path.join("/tmp",str(uuid.uuid4()))
    os.makedirs(TMP_DIR, exist_ok=True)
    input_path = download_shp_file(benchmark_bucket, input, TMP_DIR)
    config_path = store_config(config, TMP_DIR)
    # Store workflow data in /tmp due to read only filesystem restriction
    result = subprocess.run([f"SettlementDelineationNeighbours", "-i", str(input_path), "-c", str(config_path)],capture_output=True,text=True)
    return {"stdout": result.stdout, "stderr": result.stderr}