import datetime
import json
import os
import shutil
import tarfile
import uuid
from typing import List, Optional, Tuple

import numpy as np
import onnxruntime as ort
from PIL import Image

from . import storage

client = storage.storage.get_instance()

SCRIPT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__)))
class_idx = json.load(open(os.path.join(SCRIPT_DIR, "imagenet_class_index.json"), "r"))
idx2label = [class_idx[str(k)][1] for k in range(len(class_idx))]

MODEL_ARCHIVE = "resnet50.tar.gz"
MODEL_DIRECTORY = "/tmp/image_classification_model"
MODEL_SUBDIR = "resnet50"

_session: Optional[ort.InferenceSession] = None
_session_input: Optional[str] = None
_session_output: Optional[str] = None
_cached_model_key: Optional[str] = None

_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def _ensure_model(
    bucket: str, model_prefix: str, model_key: str
) -> Tuple[float, float]:
    """
    Lazily download, extract, and initialize the ONNX ResNet model.
    """
    global _session, _session_input, _session_output, _cached_model_key

    effective_model_key = model_key or MODEL_ARCHIVE
    model_download_begin = datetime.datetime.now()
    model_download_end = model_download_begin

    if _session is None or _cached_model_key != effective_model_key:
        archive_basename = os.path.basename(effective_model_key)
        archive_path = os.path.join("/tmp", f"{uuid.uuid4()}-{archive_basename}")
        model_dir = os.path.join(MODEL_DIRECTORY, MODEL_SUBDIR)

        if os.path.exists(model_dir):
            shutil.rmtree(model_dir)
        os.makedirs(MODEL_DIRECTORY, exist_ok=True)

        client.download(
            bucket, os.path.join(model_prefix, effective_model_key), archive_path
        )
        model_download_end = datetime.datetime.now()

        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(MODEL_DIRECTORY)
        os.remove(archive_path)

        model_process_begin = datetime.datetime.now()
        onnx_path = os.path.join(model_dir, "model.onnx")
        if not os.path.exists(onnx_path):
            raise FileNotFoundError(f"Expected ONNX model at {onnx_path}")

        available = ort.get_available_providers()
        if "CUDAExecutionProvider" not in available:
            raise RuntimeError(
                f"CUDAExecutionProvider unavailable (providers: {available})"
            )

        _session = ort.InferenceSession(onnx_path, providers=["CUDAExecutionProvider"])
        _session_input = _session.get_inputs()[0].name
        _session_output = _session.get_outputs()[0].name
        _cached_model_key = effective_model_key
        model_process_end = datetime.datetime.now()
    else:
        model_process_begin = datetime.datetime.now()
        model_process_end = model_process_begin

    model_download_time = (
        model_download_end - model_download_begin
    ) / datetime.timedelta(microseconds=1)
    model_process_time = (model_process_end - model_process_begin) / datetime.timedelta(
        microseconds=1
    )

    return model_download_time, model_process_time


def _resize_shorter_side(image: Image.Image, size: int) -> Image.Image:
    width, height = image.size
    if width < height:
        new_width = size
        new_height = int(round(size * height / width))
    else:
        new_height = size
        new_width = int(round(size * width / height))
    resample = getattr(Image, "Resampling", Image).BILINEAR
    return image.resize((new_width, new_height), resample=resample)


def _center_crop(image: Image.Image, size: int) -> Image.Image:
    width, height = image.size
    left = max(0, int(round((width - size) / 2)))
    top = max(0, int(round((height - size) / 2)))
    right = left + size
    bottom = top + size
    return image.crop((left, top, right, bottom))


def _prepare_tensor(image_path: str) -> np.ndarray:
    image = Image.open(image_path).convert("RGB")
    image = _resize_shorter_side(image, 256)
    image = _center_crop(image, 224)

    np_image = np.asarray(image).astype(np.float32) / 255.0
    np_image = (np_image - _MEAN) / _STD
    np_image = np.transpose(np_image, (2, 0, 1))
    return np_image[np.newaxis, :]


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits, axis=1, keepdims=True)
    exp = np.exp(shifted)
    return exp / np.sum(exp, axis=1, keepdims=True)


def _run_inference(batch: np.ndarray) -> Tuple[int, float, List[int]]:
    assert (
        _session is not None
        and _session_input is not None
        and _session_output is not None
    )

    outputs = _session.run([_session_output], {_session_input: batch})
    logits = outputs[0]
    probs = _softmax(logits)
    top1_idx = int(np.argmax(probs, axis=1)[0])
    top1_conf = float(probs[0, top1_idx])
    top5_idx = np.argsort(probs[0])[::-1][:5].tolist()

    return top1_idx, top1_conf, top5_idx


def handler(event):
    bucket = event.get("bucket", {}).get("bucket")
    input_prefix = event.get("bucket", {}).get("input")
    model_prefix = event.get("bucket", {}).get("model")
    key = event.get("object", {}).get("input")
    model_key = event.get("object", {}).get("model")

    download_path = os.path.join("/tmp", f"{uuid.uuid4()}-{os.path.basename(key)}")
    image_download_begin = datetime.datetime.now()
    client.download(bucket, os.path.join(input_prefix, key), download_path)
    image_download_end = datetime.datetime.now()

    model_download_time, model_process_time = _ensure_model(
        bucket, model_prefix, model_key
    )

    inference_begin = datetime.datetime.now()
    input_batch = _prepare_tensor(download_path)
    top1_idx, top1_conf, top5_idx = _run_inference(input_batch)
    inference_end = datetime.datetime.now()

    os.remove(download_path)

    download_time = (image_download_end - image_download_begin) / datetime.timedelta(
        microseconds=1
    )
    compute_time = (inference_end - inference_begin) / datetime.timedelta(
        microseconds=1
    )
    # gpu_time_ms = 0.0

    return {
        "result": {
            "idx": top1_idx,
            "class": idx2label[top1_idx],
            "confidence": top1_conf,
            "top5_idx": top5_idx,
        },
        "measurement": {
            "download_time": download_time + model_download_time,
            "compute_time": compute_time + model_process_time,
            "model_time": model_process_time,
            "model_download_time": model_download_time,
            # "gpu_time_ms": round(gpu_time_ms, 3),
        },
    }
