import subprocess
import json
from .SDAHelper import *

def get_splits(config_path:Path)->int:
    with open(config_path,"r") as f:
        config = json.load(f)
    return int(config.get("splits",0))

def handler(event):
    benchmark_bucket = event["benchmark_bucket"]
    INPUT_DIR = create_tmp_dir()
    OUTPUT_DIR = create_tmp_dir()
    input_path = download_file_bucket(benchmark_bucket, event["input_bucket"], event["input_file"], INPUT_DIR)
    splits = get_splits(load_config(event, INPUT_DIR))
    command = ["FishnetShapefileSplitter","-i", str(input_path), "-o", str(OUTPUT_DIR),"-s", str(splits)]
    result = subprocess.run(command,capture_output=True,text=True,cwd=INPUT_DIR)
    if result.returncode != 0:
        event["stdout"] = result.stdout
        event["stderr"] = result.stderr
        event["command"] = " ".join(command)
        return event
    split_output_files = []
    for file in Path(OUTPUT_DIR).glob("*.shp"):
        upload_shp_file(benchmark_bucket, event["split_output_bucket"], file)
        split_output_files.append(Path(file).name)
    return {
        "filter_workloads":[
            {
                "filter_input_file": split_file,
                **event
            }for split_file in split_output_files
        ],
        **event
    }