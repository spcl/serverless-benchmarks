import subprocess
def handler(event):
    input = "/data/Corvara_IT.tiff"
    config = "/data/sda-workflow-local.json"
    result = subprocess.run([f"SettlementDelineationFilter", "-i", input, "-c", config],capture_output=True,text=True)
    return {"stdout": result.stdout, "stderr": result.stderr}