import os
import uuid
from . import storage

import cv2

client = storage.storage.get_instance()


def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def load_video(benchmark_bucket, bucket, blob, dest_dir):
    path = os.path.join(dest_dir, blob)
    client.download(benchmark_bucket, bucket + '/' + blob, path)
    return path


def decode_video(path, n_frames, dest_dir):
    vidcap = cv2.VideoCapture(path)
    success, img = vidcap.read()
    img_paths = []
    while success and len(img_paths) < n_frames:
        img_path = os.path.join(dest_dir, f"frame{len(img_paths)}.jpg")
        img_paths.append(img_path)
        cv2.imwrite(img_path, img)
        success, img = vidcap.read()

    return img_paths


def upload_imgs(benchmark_bucket, bucket, paths):
    client = storage.storage.get_instance()

    for path in paths:
        name = os.path.basename(path)
        yield client.upload(benchmark_bucket, bucket + '/' + name, path)


def handler(event):
    vid_blob = event["video"]
    n_frames = event["n_frames"]
    batch_size = event["batch_size"]
    frames_bucket = event["frames_bucket"]
    input_bucket = event["input_bucket"]
    benchmark_bucket = event["benchmark_bucket"]

    tmp_dir = os.path.join("/tmp", str(uuid.uuid4()))
    os.makedirs(tmp_dir, exist_ok=True)

    vid_path = load_video(benchmark_bucket, input_bucket, vid_blob, tmp_dir)
    img_paths = decode_video(vid_path, n_frames, tmp_dir)
    paths = list(upload_imgs(benchmark_bucket, frames_bucket, img_paths))
    frames = list(chunks(paths, batch_size))

    return {
        "frames": [{
            "frames_bucket": frames_bucket,
            "frames": fs,
            "benchmark_bucket": benchmark_bucket,
            "model_bucket": input_bucket,
            "model_config": event["model_config"],
            "model_weights": event["model_weights"]
        } for fs in frames]
    }
