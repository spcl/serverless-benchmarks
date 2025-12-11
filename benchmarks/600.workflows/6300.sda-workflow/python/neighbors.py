import subprocess
from .SDAHelper import *
    
def handler(event):
    benchmark_bucket = event["benchmark_bucket"]
    filter_output_bucket = event["filter_output_bucket"]
    TMP_DIR = create_tmp_dir()
    input_path = download_shp_file(benchmark_bucket, filter_output_bucket ,event["filtered_shp_file"], TMP_DIR)
    adjacent_input_paths = [download_shp_file(benchmark_bucket, filter_output_bucket ,f, TMP_DIR) for f in event.get("adjacent_files",[])]
    config_path = load_config(event, TMP_DIR)
    # Store workflow data in /tmp due to read only filesystem restriction
    command = ["SettlementDelineationNeighbours", "-i", str(input_path), "-c", str(config_path)]
    if len(adjacent_input_paths) > 0:
        command.append("-a")
        command.extend([str(p) for p in adjacent_input_paths])
    result = subprocess.run(command,capture_output=True,text=True)
    if result.returncode != 0:
        event["stdout"] = result.stdout
        event["stderr"] = result.stderr
        event["command"] = " ".join(command)
        return event
    return {}