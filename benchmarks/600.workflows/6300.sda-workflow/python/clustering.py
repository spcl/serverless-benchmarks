import subprocess
from .SDAHelper import *

def handler(event):

    benchmark_bucket = event["benchmark_bucket"]
    filter_output_bucket = event["filter_output_bucket"]
    TMP_DIR = create_tmp_dir()
    input_files = [download_shp_file(benchmark_bucket, filter_output_bucket ,shp_file, TMP_DIR ) for shp_file in event["cluster_input_files"]]
    config = load_config(benchmark_bucket,event["input_bucket"], TMP_DIR)
    components = event["cluster_components"]
    OUTPUT_STEM = "Cluster"+str(components[0])
    # Store workflow data in /tmp due to read only filesystem restriction
    command = [f"SettlementDelineationContraction", "-i"] 
    command.extend([str(file) for file in input_files])
    command.extend(["-c", str(config),"--outputStem",OUTPUT_STEM,"--components"])
    command.extend([str(comp) for comp in components])
    result = subprocess.run(command,capture_output=True,text=True, cwd=TMP_DIR)
    if result.returncode != 0:
        event["stdout"] = result.stdout
        event["stderr"] = result.stderr
        return event
    output_file = Path(TMP_DIR).glob(f"{OUTPUT_STEM}*.shp").__next__()
    upload_shp_file(benchmark_bucket, event["cluster_output_bucket"],output_file)
    event.pop("cluster_input_files", None)
    event.pop("cluster_components", None)
    event["cluster_output_file"] = output_file.name
    return {"payload":event,"request_id":event.get("request-id","0")}