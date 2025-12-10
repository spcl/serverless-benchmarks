import subprocess
from .SDAHelper import *

def run_merge(input_files, output_file, directory,event):
    output_location = Path(directory)/output_file
    command = [f"SettlementDelineationMerge", "-i"] 
    command.extend([str(file) for file in input_files])
    command.extend(["--output",str(output_location)])
    res = subprocess.run(command,capture_output=True,text=True, cwd=directory)
    upload_shp_file(event["benchmark_bucket"], event["final_output_bucket"],output_location)
    return res

def load_input(event,directory):
    benchmark_bucket = event["benchmark_bucket"]
    analysis_output_bucket = event["analysis_output_bucket"]
    merge_input_files = []
    merge_edges_input_files = []
    for workload in event["workloads"]:
        for file in workload["analysis_output_files"]:
            shp_file = download_shp_file(benchmark_bucket,analysis_output_bucket,file,directory)
            if "_edges" in shp_file.stem:
                merge_edges_input_files.append(shp_file)
            else:
                merge_input_files.append(shp_file)
    return merge_input_files, merge_edges_input_files

def handler(event):
    TMP_DIR = create_tmp_dir()
    merge_input_files, merge_edges_input_files = load_input(event, TMP_DIR)
    OUTPUT_FILE_STEM = Path(event["input_file"]).stem + "_SDA"
    OUTPUT_FILE_NAME = OUTPUT_FILE_STEM + ".shp"
    EDGE_OUTPUT_FILE_NAME = OUTPUT_FILE_STEM + "_edges.shp"
    merge_output_result = run_merge(merge_input_files, OUTPUT_FILE_NAME, TMP_DIR,event)
    if merge_output_result.returncode != 0:
        return {"stdout": merge_output_result.stdout, "stderr": merge_output_result.stderr,"command": merge_output_result.args}
    if len(merge_edges_input_files) > 0:
        merge__edge_output_result = run_merge(merge_edges_input_files, EDGE_OUTPUT_FILE_NAME, TMP_DIR,event)
    return {"OutputFile":OUTPUT_FILE_NAME,"EdgeOutputFile":EDGE_OUTPUT_FILE_NAME}