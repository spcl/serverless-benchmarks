import subprocess
from .SDAHelper import *

def handler(event):
    benchmark_bucket = event["benchmark_bucket"]
    cluster_output_bucket = event["cluster_output_bucket"]
    TMP_DIR = create_tmp_dir()
    analysis_input_file = download_shp_file(benchmark_bucket,cluster_output_bucket,event["cluster_output_file"],TMP_DIR)
    config_file = load_config(event, TMP_DIR)
    OUTPUT_STEM = "Analysis_"+Path(analysis_input_file).stem
    command = ["SettlementDelineationAnalysis", "-i", str(analysis_input_file), "-c", str(config_file), "--outputStem", OUTPUT_STEM]
    result = subprocess.run(command,capture_output=True,text=True, cwd=TMP_DIR)
    if result.returncode != 0:
        event["stdout"] = result.stdout
        event["stderr"] = result.stderr
        return event
    event.pop("cluster_output_file", None)
    event["analysis_output_files"]= []
    for file in Path(TMP_DIR).glob(f"{OUTPUT_STEM}*.shp"):
        upload_shp_file(benchmark_bucket, event["analysis_output_bucket"],file)
        event["analysis_output_files"].append(file.name)
    return event
