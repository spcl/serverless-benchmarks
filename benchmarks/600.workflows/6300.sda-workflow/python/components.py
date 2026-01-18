import subprocess
from .SDAHelper import *
import json

def build_cluster_workload(components_files):
    workloads = []
    for comp_file in components_files:
        with open(comp_file, 'r') as f:
            components_data = json.load(f)
        workload = {
            "cluster_input_files": [Path(f).name for f in components_data["files"]],
            "cluster_components": components_data["components"]
        }
        workloads.append(workload)
    return workloads

def handler(event):
    TMP_DIR = create_tmp_dir()
    config_file = load_config(event, TMP_DIR)
    COMPONENT_FILE_PREFIX = "components"
    result = subprocess.run(
        ["AfricapolisGraphComponents", "-c", str(config_file), "-o", COMPONENT_FILE_PREFIX],
        cwd=TMP_DIR,
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        event["stdout"] = result.stdout
        event["stderr"] = result.stderr
        return event
    event.pop("stdout", None)
    event.pop("stderr", None)
    event.pop("neighbors_workloads", None)
    components_files = sorted(str(p) for p in Path(TMP_DIR).glob(f"{COMPONENT_FILE_PREFIX}*.json"))
    workloads = build_cluster_workload(components_files)
    return {
        "cluster_workloads":[
            {
                "cluster_input_files": workload["cluster_input_files"],
                "cluster_components": workload["cluster_components"],
                **event
            } for workload in workloads
        ],
        **event
    }