import os
import uuid
import subprocess
from . import storage
import logging
import shutil

XC_ENC_REBASE = "/tmp/xc-enc -W -w 0.75 -i y4m -o {output}.ivf -r -I {source_state}.state -p {input_pred}.ivf -S {pred_state}.state {extra} {input}.y4m"

client = storage.storage.get_instance()

def download_bin(bucket, name, dest_dir):
    path = os.path.join(dest_dir, name)
    if not os.path.exists(path):
        client.download(bucket, name, path)
        subprocess.check_output(f"chmod +x {path}", stderr=subprocess.STDOUT, shell=True)


def upload_files(bucket, paths):
    for path in paths:
        name = os.path.basename(path)
        client.upload(bucket, name, path, unique_name=False)


def run(cmd):
    try:
        return subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True)
    except subprocess.CalledProcessError as e:
        logger = logging.getLogger()
        logger.error(f"Error when executing command: {cmd}\n{e.output.decode('utf-8')}")
        raise e


def prev_seg_name(seg):
    idx = int(seg)-1
    assert(idx >= 0)
    return "{:08d}".format(idx)


def rebase(segs, data_dir):
    for idx in range(1, len(segs)):
        input = segs[idx]
        input_path = os.path.join(data_dir, input)
        prev_input_path = os.path.join(data_dir, prev_seg_name(input))
        extra = f"-O {input_path}-1.state" if idx < len(segs)-1 else ""

        cmd = XC_ENC_REBASE.format(
            output=input_path,
            input=input_path,
            source_state=f"{prev_input_path}-1",
            extra=extra,
            input_pred=f"{input_path}-1",
            pred_state=f"{prev_input_path}-0")
        run(cmd)


def handler(event):
    input_bucket = event["input_bucket"]
    output_bucket = event["output_bucket"]
    segs = event["segments"]
    segs = [os.path.splitext(seg)[0] for seg in segs]
    should_rebase = event["rebase"]

    if not should_rebase:
        return

    tmp_dir = "/tmp"
    download_bin(input_bucket, "xc-enc", tmp_dir)

    data_dir = os.path.join(tmp_dir, str(uuid.uuid4()))
    os.makedirs(data_dir, exist_ok=True)
    for seg in segs[1:]:
        for ext in ["-1.ivf", "-0.state"]:
            name = seg+ext
            path = os.path.join(data_dir, name)
            client.download(output_bucket, name, path)

        name = seg+".y4m"
        path = os.path.join(data_dir, name)
        client.download(input_bucket, name, path)

    first_state = segs[0]+"-1.state"
    path = os.path.join(data_dir, first_state)
    client.download(output_bucket, first_state, path)
    first_state = segs[0]+"-0.state"
    path = os.path.join(data_dir, first_state)
    client.download(output_bucket, first_state, path)
    rebase(segs, data_dir)

    output_paths = [os.path.join(data_dir, p+".ivf") for p in segs[1:]]
    output_paths += [os.path.join(data_dir, p+"-1.state") for p in segs[1:-1]]
    upload_files(output_bucket, output_paths)

    shutil.rmtree(data_dir)
