import os
import uuid
import subprocess
from . import storage
import logging
import shutil

VPXENC = "/tmp/vpxenc --ivf --codec=vp8 --good --cpu-used=0 --end-usage=cq --min-q=0 --max-q=63 --cq-level={quality} --buf-initial-sz=10000 --buf-optimal-sz=20000 --buf-sz=40000 --undershoot-pct=100 --passes=2 --auto-alt-ref=1 --threads=1 --token-parts=0 --tune=ssim --target-bitrate=4294967295 -o {output}.ivf {input}.y4m"
TERMINATE_CHUNK = "/tmp/xc-terminate-chunk {input}.ivf {output}.ivf"
XC_DUMP_0 = "/tmp/xc-dump {input}.ivf {output}.state"

client = storage.storage.get_instance()

def download_bin(bucket, name, dest_dir):
    path = os.path.join(dest_dir, name)
    if not os.path.exists(path):
        client.download(bucket, name, path)
        subprocess.check_output(f"chmod +x {path}", stderr=subprocess.STDOUT, shell=True)


def upload_files(bucket, paths):
    for path in paths:
        file = os.path.basename(path)
        print("Uploading", file, "to", path)
        client.upload(bucket, file, path, unique_name=False)


def run(cmd):
    try:
        return subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True)
    except subprocess.CalledProcessError as e:
        logger = logging.getLogger()
        logger.error(f"Error when executing command: {cmd}\n{e.output.decode('utf-8')}")
        raise e


def encode(segs, data_dir, quality):
    files = []

    for idx, name in enumerate(segs):
        input_path = os.path.join(data_dir, name)
        output_path = os.path.join(data_dir, f"{name}-vpxenc")
        cmd = VPXENC.format(quality=quality, input=input_path, output=output_path)
        run(cmd)

        input_path = output_path
        output = name if idx == 0 else f"{name}-0"
        output_path = os.path.join(data_dir, output)
        cmd = TERMINATE_CHUNK.format(input=input_path, output=output_path)
        run(cmd)
        files.append(output_path+".ivf")

        input_path = output_path
        output_path = os.path.join(data_dir, f"{name}-0")
        cmd = XC_DUMP_0.format(input=input_path, output=output_path)
        run(cmd)
        files.append(output_path+".state")

    return files


def handler(event):
    input_bucket = event["input_bucket"]
    output_bucket = event["output_bucket"]
    segs = event["segments"]
    quality = event["quality"]

    tmp_dir = "/tmp"
    download_bin(input_bucket, "vpxenc", tmp_dir)
    download_bin(input_bucket, "xc-terminate-chunk", tmp_dir)
    download_bin(input_bucket, "xc-dump", tmp_dir)

    data_dir = os.path.join(tmp_dir, str(uuid.uuid4()))
    os.makedirs(data_dir, exist_ok=True)
    for seg in segs:
        path = os.path.join(data_dir, seg)
        client.download(input_bucket, seg, path)

    segs = [os.path.splitext(seg)[0] for seg in segs]
    output_paths = encode(segs, data_dir, quality)
    upload_files(output_bucket, output_paths)

    shutil.rmtree(data_dir)

    return event
