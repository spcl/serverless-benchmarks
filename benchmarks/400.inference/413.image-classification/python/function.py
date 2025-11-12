import datetime
import json
import os
import uuid
from typing import List, Optional, Tuple

# Extract zipped torch model - used in Python 3.8 and 3.9
# if os.path.exists("function/torch.zip"):
#     import zipfile, sys

#     zipfile.ZipFile("function/torch.zip").extractall("/tmp/")
#     sys.path.append(
#         os.path.join(os.path.dirname(__file__), "/tmp/.python_packages/lib/site-packages")
#     )

from PIL import Image
import torch
from torchvision import transforms
from torchvision.models import resnet50

from . import storage

client = storage.storage.get_instance()

SCRIPT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__)))
class_idx = json.load(open(os.path.join(SCRIPT_DIR, "imagenet_class_index.json"), "r"))
idx2label = [class_idx[str(k)][1] for k in range(len(class_idx))]

MODEL_DIRECTORY = "resnet50.tar.gz"
_model: Optional[torch.nn.Module] = None
_model_key: Optional[str] = None
_device = "cuda" if torch.cuda.is_available() else "cpu"
_preprocess = transforms.Compose(
    [
        transforms.Resize(256),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ]
)


def _ensure_model(bucket: str, model_prefix: str, model_key: str) -> Tuple[float, float]:
    """
    Lazily download and load the ResNet model so repeated invocations stay warm.
    """
    global _model, _model_key

    model_download_begin = datetime.datetime.now()
    model_download_end = model_download_begin
    model_process_begin = datetime.datetime.now()
    model_process_end = model_process_begin

    if _model is None or _model_key != model_key:
        os.makedirs(MODEL_DIRECTORY, exist_ok=True)
        weights_name = os.path.basename(model_key)
        weights_path = os.path.join(MODEL_DIRECTORY, weights_name)

        if not os.path.exists(weights_path):
            client.download(bucket, os.path.join(model_prefix, model_key), weights_path)
            model_download_end = datetime.datetime.now()
        else:
            model_download_begin = datetime.datetime.now()
            model_download_end = model_download_begin

        model_process_begin = datetime.datetime.now()
        model = resnet50(pretrained=False)
        state = torch.load(weights_path, map_location="cpu")
        state = state.get("state_dict", state)
        model.load_state_dict(state)
        model.eval()
        model.to(_device)
        if _device == "cuda":
            torch.backends.cudnn.benchmark = True
        _model = model
        _model_key = model_key
        model_process_end = datetime.datetime.now()

    return (
        (model_download_end - model_download_begin) / datetime.timedelta(microseconds=1),
        (model_process_end - model_process_begin) / datetime.timedelta(microseconds=1),
    )


def _prepare_tensor(image_path: str) -> torch.Tensor:
    image = Image.open(image_path).convert("RGB")
    tensor = _preprocess(image).unsqueeze(0)
    return tensor.to(_device, non_blocking=True)


def _run_inference(batch: torch.Tensor) -> Tuple[int, float, List[int], float]:
    assert _model is not None

    gpu_time_ms = 0.0
    start_evt = end_evt = None
    if _device == "cuda":
        torch.cuda.synchronize()
        start_evt = torch.cuda.Event(enable_timing=True)
        end_evt = torch.cuda.Event(enable_timing=True)
        start_evt.record()

    with torch.no_grad():
        output = _model(batch)

    if _device == "cuda" and start_evt and end_evt:
        end_evt.record()
        torch.cuda.synchronize()
        gpu_time_ms = float(start_evt.elapsed_time(end_evt))

    probs = torch.nn.functional.softmax(output, dim=1)
    conf, index = torch.max(probs, 1)
    _, top5_idx = torch.topk(probs, k=5, dim=1)

    return index.item(), float(conf.item()), top5_idx[0].tolist(), gpu_time_ms


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

    model_download_time, model_process_time = _ensure_model(bucket, model_prefix, model_key)

    inference_begin = datetime.datetime.now()
    input_batch = _prepare_tensor(download_path)
    top1_idx, top1_conf, top5_idx, gpu_time_ms = _run_inference(input_batch)
    inference_end = datetime.datetime.now()

    os.remove(download_path)

    download_time = (image_download_end - image_download_begin) / datetime.timedelta(microseconds=1)
    compute_time = (inference_end - inference_begin) / datetime.timedelta(microseconds=1)

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
            "gpu_time_ms": round(gpu_time_ms, 3),
        },
    }
