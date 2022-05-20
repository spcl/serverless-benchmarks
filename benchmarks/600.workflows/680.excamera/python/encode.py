import os
import uuid
import subprocess
from . import storage
import logging

VPXENC = '/tmp/vpxenc --ivf --codec=vp8 --good --cpu-used=0 --end-usage=cq --min-q=0 --max-q=63 --cq-level={quality} --buf-initial-sz=10000 --buf-optimal-sz=20000 --buf-sz=40000 --undershoot-pct=100 --passes=2 --auto-alt-ref=1 --threads=1 --token-parts=0 --tune=ssim --target-bitrate=4294967295 -o {output}.ivf {input}.y4m'
TERMINATE_CHUNK = "/tmp/xc-terminate-chunk {input}.ivf {output}.ivf"
XC_DUMP_0 = '/tmp/xc-dump {input}.ivf {output}.state'
XC_ENC_FIRST_FRAME = '/tmp/xc-enc -W -w 0.75 -i y4m -o {output}.ivf -r -I {source_state}.state -p {input_pred}.ivf {extra} {input}.y4m'
XC_ENC_REBASE = '/tmp/xc-enc -W -w 0.75 -i y4m -o {output}.ivf -r -I {source_state}.state -p {input_pred}.ivf -S {pred_state}.state {extra} {input}.y4m'

client = storage.storage.get_instance()

def download_bin(bucket, name, dest_dir):
    path = os.path.join(dest_dir, name)
    client.download(bucket, name, path)
    subprocess.check_output(f"chmod +x {path}", stderr=subprocess.STDOUT, shell=True)


def run(cmd):
    try:
        return subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True)
    except subprocess.CalledProcessError as e:
        logger = logging.getLogger()
        logger.error(f"Error when executing command: {cmd}\n{e.output.decode('utf-8')}")
        raise e


def vpxenc(segs, data_dir):
    for idx, input in enumerate(segs):
        output = f"{input}-vpxenc"
        input_path = os.path.join(data_dir, input)
        output_path = os.path.join(data_dir, output)
        cmd = VPXENC.format(quality=63, input=input_path, output=output_path)
        run(cmd)

        input_path = output_path
        output = input if idx == 0 else f"{input}-0"
        output_path = os.path.join(data_dir, output)
        cmd = TERMINATE_CHUNK.format(input=input_path, output=output_path)
        run(cmd)

        input_path = output_path
        output = f"{input}-0"
        output_path = os.path.join(data_dir, output)
        cmd = XC_DUMP_0.format(input=input_path, output=output_path)
        run(cmd)


def reencode_first_frame(segs, data_dir):
    for idx in range(1, len(segs)):
        input_path = os.path.join(data_dir, segs[idx])
        prev_input_path = os.path.join(data_dir, segs[idx-1])
        output_path = input_path if idx == 1 else f"{input_path}-1"
        extra = f"-O {input_path}-1.state" if idx == 1 else ""

        cmd = XC_ENC_FIRST_FRAME.format(
            input=input_path,
            output=output_path,
            source_state=f"{prev_input_path}-0",
            extra=extra,
            input_pred=f"{input_path}-0")
        run(cmd)


def rebase(segs, data_dir):
    for idx in range(2, len(segs)):
        input_path = os.path.join(data_dir, segs[idx])
        prev_input_path = os.path.join(data_dir, segs[idx-1])
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

    tmp_dir = "/tmp"
    download_bin(input_bucket, "vpxenc", tmp_dir)
    download_bin(input_bucket, "xc-terminate-chunk", tmp_dir)
    download_bin(input_bucket, "xc-dump", tmp_dir)
    download_bin(input_bucket, "xc-enc", tmp_dir)

    data_dir = os.path.join(tmp_dir, str(uuid.uuid4()))
    os.makedirs(data_dir, exist_ok=True)
    for seg in segs:
        path = os.path.join(data_dir, seg)
        client.download(input_bucket, seg, path)

    segs = [os.path.splitext(seg)[0] for seg in segs]
    vpxenc(segs, data_dir)
    reencode_first_frame(segs, data_dir)
    rebase(segs, data_dir)

    return {
        "res": "lol"
    }
