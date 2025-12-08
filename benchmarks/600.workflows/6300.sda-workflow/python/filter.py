import subprocess
from .SDAHelper import *
    
def handler(event):
    benchmark_bucket = event["benchmark_bucket"]
    input_bucket = event["input_bucket"]
    output_bucket = event["filter_output_bucket"]
    input = event["input_file"]
    config = event["config_file"]
    TMP_DIR = create_tmp_dir()
    input_path = download_file_bucket(benchmark_bucket, input_bucket, input, TMP_DIR)
    config_path = store_config(config, TMP_DIR)
    # Store workflow data in /tmp due to read only filesystem restriction
    result = subprocess.run([f"SettlementDelineationFilter", "-i", str(input_path), "-c", str(config_path), "-o", TMP_DIR],capture_output=True,text=True)
    output_file = Path(TMP_DIR).glob("*_filtered.shp").__next__()
    output_files = list(upload_shp_file(benchmark_bucket, output_bucket, output_file))
    return {"stdout": result.stdout, "stderr": result.stderr,"filtered_files":output_files,"benchmark_bucket":benchmark_bucket,"config_file":config}