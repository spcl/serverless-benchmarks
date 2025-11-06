import datetime, json, os, uuid

# Extract zipped torch model - used in Python 3.8 and 3.9
if os.path.exists("function/torch.zip"):
    import zipfile, sys

    zipfile.ZipFile("function/torch.zip").extractall("/tmp/")
    sys.path.append(
        os.path.join(os.path.dirname(__file__), "/tmp/.python_packages/lib/site-packages")
    )

from PIL import Image
import torch
from torchvision import transforms
from torchvision.models import resnet50

from . import storage

client = storage.storage.get_instance()

SCRIPT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__)))
class_idx = json.load(open(os.path.join(SCRIPT_DIR, "imagenet_class_index.json"), "r"))
idx2label = [class_idx[str(k)][1] for k in range(len(class_idx))]

model = None
device = "cuda" if torch.cuda.is_available() else "cpu"


def handler(event):
    bucket = event.get("bucket").get("bucket")
    input_prefix = event.get("bucket").get("input")
    model_prefix = event.get("bucket").get("model")
    key = event.get("object").get("input")
    model_key = event.get("object").get("model")

    download_path = "/tmp/{}-{}".format(key, uuid.uuid4())

    # --- Download image ---
    image_download_begin = datetime.datetime.now()
    image_path = download_path
    client.download(bucket, os.path.join(input_prefix, key), download_path)
    image_download_end = datetime.datetime.now()

    global model
    if model is None:
        # --- Download weights ---
        model_download_begin = datetime.datetime.now()
        model_path = os.path.join("/tmp", model_key)
        client.download(bucket, os.path.join(model_prefix, model_key), model_path)
        model_download_end = datetime.datetime.now()

        # --- Load model (CPU), then move to GPU ---
        model_process_begin = datetime.datetime.now()
        model = resnet50(pretrained=False)
        state = torch.load(model_path, map_location="cpu")  # robust for CPU-saved checkpoints
        # handle checkpoints that wrap state dict:
        state = state.get("state_dict", state)
        model.load_state_dict(state)
        model.eval()
        model.to(device)
        # speed on cuDNN-convolutional nets
        if device == "cuda":
            torch.backends.cudnn.benchmark = True
        model_process_end = datetime.datetime.now()
    else:
        # model already cached
        model_download_begin = model_download_end = datetime.datetime.now()
        model_process_begin = model_process_end = datetime.datetime.now()

    # --- Preprocess (CPU) ---
    process_begin = datetime.datetime.now()
    input_image = Image.open(image_path).convert("RGB")
    preprocess = transforms.Compose(
        [
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),  # [0,1], CHW
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ]
    )
    input_tensor = preprocess(input_image)  # CPU tensor
    input_batch = input_tensor.unsqueeze(0).to(device, non_blocking=True)  # NCHW on GPU

    # --- Inference (GPU) ---
    with torch.no_grad():
        # Ensure wall-clock timing includes GPU work
        if device == "cuda":
            torch.cuda.synchronize()
        # GPU event timing (kernel time)
        start_evt = end_evt = None
        if device == "cuda":
            start_evt = torch.cuda.Event(enable_timing=True)
            end_evt = torch.cuda.Event(enable_timing=True)
            start_evt.record()

        output = model(input_batch)  # logits [1,1000]

        if device == "cuda":
            end_evt.record()
            torch.cuda.synchronize()

    # compute top-1 / top-5 on CPU
    probs = torch.nn.functional.softmax(output, dim=1)
    conf, index = torch.max(probs, 1)
    # make Python types
    top1_idx = index.item()
    top1_conf = float(conf.item())
    # (optional) top-5
    _, top5_idx = torch.topk(probs, k=5, dim=1)
    top5_idx = top5_idx[0].tolist()

    ret = idx2label[top1_idx]  # <- use .item() result

    process_end = datetime.datetime.now()

    # timings
    download_time = (image_download_end - image_download_begin) / datetime.timedelta(microseconds=1)
    model_download_time = (model_download_end - model_download_begin) / datetime.timedelta(
        microseconds=1
    )
    model_process_time = (model_process_end - model_process_begin) / datetime.timedelta(
        microseconds=1
    )
    process_time = (process_end - process_begin) / datetime.timedelta(microseconds=1)

    # optional precise GPU kernel time (ms)
    gpu_time_ms = 0.0
    if start_evt is not None and end_evt is not None:
        gpu_time_ms = float(start_evt.elapsed_time(end_evt))  # milliseconds

    return {
        "result": {"idx": top1_idx, "class": ret, "confidence": top1_conf, "top5_idx": top5_idx},
        "measurement": {
            "download_time": download_time + model_download_time,  # µs
            "compute_time": process_time + model_process_time,  # µs (wall time, includes GPU)
            "model_time": model_process_time,  # µs
            "model_download_time": model_download_time,  # µs
            "gpu_time_ms": round(gpu_time_ms, 3),  # extra: CUDA kernel time
        },
    }
