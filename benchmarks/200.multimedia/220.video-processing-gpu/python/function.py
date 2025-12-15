#!/usr/bin/env python

import datetime
import os
import stat  # can also be removed if you drop ffmpeg entirely
from typing import Dict, Any

import numpy as np
import cv2
import torch
import torch.nn as nn

from . import storage

client = storage.storage.get_instance()
SCRIPT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__)))


def gpu_video_filter(video_path: str, duration: float, event: Dict[str, Any]) -> str:
    """
    Decode a video on CPU (OpenCV), run a heavy GPU filter with PyTorch,
    and re-encode the processed video.

    This gives you a realistic FaaS workload:
      - I/O via storage
      - CPU video decode/encode
      - GPU-heavy tensor processing
    """

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open input video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 0:
        fps = 25.0  # fallback

    max_frames = int(fps * duration)
    frames = []

    for i in range(max_frames):
        ret, frame_bgr = cap.read()
        if not ret:
            break
        # Convert BGR (OpenCV default) to RGB
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        frames.append(frame_rgb)

    cap.release()

    if not frames:
        raise RuntimeError("No frames decoded from video (empty or too short?)")

    # Stack into (T, H, W, C)
    video_np = np.stack(frames, axis=0)  # uint8, 0–255
    T, H, W, C = video_np.shape

    # Convert to torch tensor: (T, C, H, W), float32 in [0, 1]
    video = torch.from_numpy(video_np).permute(0, 3, 1, 2).float() / 255.0

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    video = video.to(device)

    # Simple heavy-ish GPU workload: repeated 3x3 conv + ReLU
    # You can tweak num_channels, num_iters, etc. via the event
    num_iters = event.get("object", {}).get("num_iters", 10)
    num_channels = 3  # keep 3 so we can write back as RGB

    conv = nn.Conv2d(
        in_channels=num_channels,
        out_channels=num_channels,
        kernel_size=3,
        padding=1,
        bias=False,
    ).to(device)

    with torch.no_grad():
        for _ in range(num_iters):
            video = torch.relu(conv(video))

    # Back to uint8 on CPU: (T, H, W, C)
    video = (video.clamp(0.0, 1.0) * 255.0).byte()
    video_np_out = video.permute(0, 2, 3, 1).cpu().numpy()

    # Encode processed video with OpenCV (CPU)
    base = os.path.splitext(os.path.basename(video_path))[0]
    out_path = f"/tmp/processed-{base}.mp4"

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(out_path, fourcc, fps, (W, H))
    if not writer.isOpened():
        raise RuntimeError(f"Could not open VideoWriter for: {out_path}")

    for frame_rgb in video_np_out:
        frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        writer.write(frame_bgr)

    writer.release()
    return out_path


# You can still support multiple ops if you want in the future.
# For now, we map "gpu-filter" (or "transcode" if you want to reuse the old name)
operations = {
    "gpu-filter": gpu_video_filter,
    # If you want to keep old names:
    # "transcode": gpu_video_filter,
    # "watermark": gpu_video_filter,
    # "extract-gif": gpu_video_filter,
}


def handler(event: Dict[str, Any]):
    """
    FaaS entrypoint.

    Expected event structure (SeBS-style):

    {
      "bucket": {
        "bucket": "<bucket-name>",
        "input": "<input-prefix>",
        "output": "<output-prefix>"
      },
      "object": {
        "key": "<object-key>",
        "duration": <seconds>,
        "op": "gpu-filter",
        // optional:
        // "num_iters": 20
      }
    }
    """

    bucket = event.get("bucket", {}).get("bucket")
    input_prefix = event.get("bucket", {}).get("input")
    output_prefix = event.get("bucket", {}).get("output")

    obj = event.get("object", {})
    key = obj.get("key")
    duration = obj.get("duration", 5)  # default: 5 seconds
    op = obj.get("op", "gpu-filter")

    if op not in operations:
        raise ValueError(f"Unknown operation '{op}'. Supported: {', '.join(operations.keys())}")

    download_path = f"/tmp/{key}"

    # If you no longer ship ffmpeg/ffmpeg, you can remove this chmod block completely.
    # Leaving it here is harmless if the file doesn't exist (it will just fail and pass).
    ffmpeg_binary = os.path.join(SCRIPT_DIR, "ffmpeg", "ffmpeg")
    try:
        st = os.stat(ffmpeg_binary)
        os.chmod(ffmpeg_binary, st.st_mode | stat.S_IEXEC)
    except OSError:
        # Ignore if ffmpeg is not present or filesystem is read-only.
        pass

    # --- Download phase ---
    download_begin = datetime.datetime.now()
    client.download(bucket, os.path.join(input_prefix, key), download_path)
    download_size = os.path.getsize(download_path)
    download_stop = datetime.datetime.now()

    # --- Compute phase (GPU via PyTorch) ---
    process_begin = datetime.datetime.now()
    upload_path = operations[op](download_path, duration, event)
    process_end = datetime.datetime.now()

    # --- Upload phase ---
    upload_begin = datetime.datetime.now()
    filename = os.path.basename(upload_path)
    upload_size = os.path.getsize(upload_path)
    upload_key = client.upload(bucket, os.path.join(output_prefix, filename), upload_path)
    upload_stop = datetime.datetime.now()

    # Convert timedeltas to microseconds
    download_time = (download_stop - download_begin) / datetime.timedelta(microseconds=1)
    upload_time = (upload_stop - upload_begin) / datetime.timedelta(microseconds=1)
    process_time = (process_end - process_begin) / datetime.timedelta(microseconds=1)

    return {
        "result": {
            "bucket": bucket,
            "key": upload_key,
        },
        "measurement": {
            "download_time": download_time,
            "download_size": download_size,
            "upload_time": upload_time,
            "upload_size": upload_size,
            "compute_time": process_time,
        },
    }
