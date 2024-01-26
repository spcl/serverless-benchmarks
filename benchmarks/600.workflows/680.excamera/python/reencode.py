import os
import uuid
import subprocess
from . import storage
import logging
import shutil

XC_ENC_FIRST_FRAME = "/tmp/xc-enc -W -w 0.75 -i y4m -o {output}.ivf -r -I {source_state}.state -p {input_pred}.ivf {extra} {input}.y4m"

client = storage.storage.get_instance()

def download_bin(bucket, name, dest_dir):
    path = os.path.join(dest_dir, name)
    if not os.path.exists(path):
        client.download(bucket, name, path)
        subprocess.check_output(f"chmod +x {path}", stderr=subprocess.STDOUT, shell=True)


def upload_files(bucket, paths, prefix):
    for path in paths:
        file = os.path.basename(path)
        file = prefix + file
        client.upload(bucket, file, path, unique_name=False)


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


def reencode_first_frame(segs, data_dir, dry_run=False):
    input_paths = []
    output_paths = []
    for idx in range(1, len(segs)):
        name = segs[idx]
        input_path = os.path.join(data_dir, name)
        output_path = input_path if idx == 1 else f"{input_path}-1"
        source_state_path = os.path.join(data_dir, prev_seg_name(name))+"-0"
        output_state_path = f"{input_path}-1.state"
        extra = f"-O {output_state_path}" if idx == 1 else ""
        input_pred_path = f"{input_path}-0"

        cmd = XC_ENC_FIRST_FRAME.format(
            input=input_path,
            output=output_path,
            source_state=source_state_path,
            extra=extra,
            input_pred=input_pred_path)
        if not dry_run:
            run(cmd)

        input_paths.append(input_path+".y4m")
        input_paths.append(source_state_path+".state")
        input_paths.append(input_pred_path+".ivf")

        output_paths.append(output_path+".ivf")
        if idx == 1:
            output_paths.append(output_state_path)

    return input_paths, output_paths


def handler(event):
    input_bucket = event["input_bucket"]
    output_bucket = event["output_bucket"]
    segs = event["segments"]
    segs = [os.path.splitext(seg)[0] for seg in segs]
    prefix = event["prefix"]

    tmp_dir = "/tmp"
    download_bin(input_bucket, "xc-enc", tmp_dir)

    data_dir = os.path.join(tmp_dir, str(uuid.uuid4()))
    os.makedirs(data_dir, exist_ok=True)
    input_paths, _ = reencode_first_frame(segs, data_dir, dry_run=True)
    for path in input_paths:
        file = os.path.basename(path)
        
        if ".y4m" in file:
            client.download(input_bucket, file, path)
        else:
            file = prefix + file
            client.download(output_bucket, file, path)        
        
        

    _, output_paths = reencode_first_frame(segs, data_dir)
    upload_files(output_bucket, output_paths, prefix)

    shutil.rmtree(data_dir)

    return event
