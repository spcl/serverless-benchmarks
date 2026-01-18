from .SDAHelper import *
import subprocess

def handler(event):
    TMP_DIR = create_tmp_dir()
    config = load_config(event, TMP_DIR)
    result = subprocess.run([f"AfricapolisClearDatabase", "-c", str(config)],capture_output=True,text=True)
    if result.returncode != 0:
        event["stdout"] = result.stdout
        event["stderr"] = result.stderr
    return event