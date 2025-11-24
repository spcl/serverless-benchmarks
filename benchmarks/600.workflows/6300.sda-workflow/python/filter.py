import subprocess
def handler(event):
    subprocess.run(["SettlementDelineationFilter"])
    return {}