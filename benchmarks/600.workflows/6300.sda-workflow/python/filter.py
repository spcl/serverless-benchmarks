import subprocess
from .SDAHelper import *
    
def handler(event):
    benchmark_bucket = event["benchmark_bucket"]
    input = event["filter_input_file"]
    TMP_DIR = create_tmp_dir()
    input_path = download_shp_file(benchmark_bucket, event["split_output_bucket"], input, TMP_DIR)
    config_path = load_config(event, TMP_DIR)
    # Store workflow data in /tmp due to read only filesystem restriction
    result = subprocess.run([f"SettlementDelineationFilter", "-i", str(input_path), "-c", str(config_path), "-o", TMP_DIR],capture_output=True,text=True)
    if result.returncode != 0:
        event["stdout"] = result.stdout
        event["stderr"] = result.stderr
        return event
    output_file = Path(TMP_DIR).glob("*_filtered.shp").__next__()
    upload_shp_file(benchmark_bucket, event["filter_output_bucket"], output_file)
    return {"filtered_shp_file":Path(output_file).name,**event}