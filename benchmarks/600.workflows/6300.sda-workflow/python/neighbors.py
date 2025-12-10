import subprocess
from .SDAHelper import *
    
def handler(event):
    benchmark_bucket = event["benchmark_bucket"]
    filter_output_bucket = event["filter_output_bucket"]
    shp_file = event["filtered_shp_file"]
    TMP_DIR = create_tmp_dir()
    input_path = download_shp_file(benchmark_bucket, filter_output_bucket ,shp_file, TMP_DIR)
    config_path = load_config(benchmark_bucket,event["input_bucket"], TMP_DIR)
    # Store workflow data in /tmp due to read only filesystem restriction
    result = subprocess.run([f"SettlementDelineationNeighbours", "-i", str(input_path), "-c", str(config_path)],capture_output=True,text=True)
    if result.returncode != 0:
        event["stdout"] = result.stdout
        event["stderr"] = result.stderr
    event.pop("filtered_shp_file", None)
    return event