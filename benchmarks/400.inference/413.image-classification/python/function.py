import datetime, json, os, tarfile
from pathlib import Path

from PIL import Image
import torch
from torchvision import transforms
from torchvision.models import resnet50

# ---------- Config ----------
# Optional env overrides; event fields take precedence if provided
ENV_MODEL_PATH = os.getenv("MODEL_PATH")  # /abs/path/resnet50.tar.gz or .pth/.pt
ENV_IMAGE_PATH = os.getenv("IMAGE_PATH")  # /abs/path/test.jpg
USE_AMP = True  # autocast for faster inference on CUDA
# ----------------------------

SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))
class_idx = json.load(open(os.path.join(SCRIPT_DIR, "imagenet_class_index.json"), "r"))
idx2label = [class_idx[str(k)][1] for k in range(len(class_idx))]

DEVICE = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
torch.backends.cudnn.benchmark = True

model = None  # cache across invocations (same as your original)


def _extract_pth_from_tar(tar_path: str, out_dir: str = "/tmp/resnet50_unpack") -> str:
    """Extract .tar.gz/.tgz and return the first .pth/.pt found."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "r:gz") as tar:
        tar.extractall(out)
    for ext in ("*.pth", "*.pt"):
        found = list(out.rglob(ext))
        if found:
            return str(found[0])
    raise FileNotFoundError(f"No .pth/.pt found in archive: {tar_path}")


def _load_resnet50_from_path(model_path: str) -> torch.nn.Module:
    """Load torchvision ResNet-50 from a local .tar.gz or .pth/.pt (CPU), then return it."""
    if model_path.endswith((".tar.gz", ".tgz")):
        weight_path = _extract_pth_from_tar(model_path)
    else:
        weight_path = model_path

    ckpt = torch.load(weight_path, map_location="cpu")
    if isinstance(ckpt, dict):
        state = ckpt.get("state_dict", ckpt.get("model", ckpt))
        if not isinstance(state, dict):
            state = ckpt
        if len(state) > 0 and next(iter(state)).startswith("module."):
            state = {k.replace("module.", "", 1): v for k, v in state.items()}
        m = resnet50(pretrained=False)
        m.load_state_dict(state, strict=False)
        m.eval()
        return m
    elif isinstance(ckpt, torch.nn.Module):
        ckpt.eval()
        return ckpt
    else:
        raise TypeError(f"Unsupported checkpoint type: {type(ckpt)}")


def _maybe_sync():
    if DEVICE.type == "cuda":
        torch.cuda.synchronize()


def handler(event):
    """
    Accepts local paths via event (preferred for your benchmark runner):
      event = {
        "local_model_archive": "/abs/path/resnet50.tar.gz" or ".pth",
        "local_image_path": "/abs/path/image.jpg"
      }
    Falls back to env MODEL_PATH / IMAGE_PATH if not provided.
    Returns the SAME structure as your existing function.py.
    """
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA not available. Run on a GPU machine/container.")

    # -------- resolve inputs --------
    model_path = event.get("local_model_archive") or ENV_MODEL_PATH
    image_path = event.get("local_image_path") or ENV_IMAGE_PATH
    assert model_path, "Provide local_model_archive in event or set MODEL_PATH"
    assert image_path, "Provide local_image_path in event or set IMAGE_PATH"

    # -------- timings: image "download" (local -> count as zero) --------
    image_download_begin = datetime.datetime.now()
    image_download_end = image_download_begin  # local file, no download

    # -------- lazy model load (cache like your original) --------
    global model
    if model is None:
        model_download_begin = datetime.datetime.now()
        model_download_end = model_download_begin  # local file, no remote download

        model_process_begin = datetime.datetime.now()
        # load on CPU, then move to GPU
        m = _load_resnet50_from_path(model_path)
        model = m.to(DEVICE, non_blocking=True).eval()
        _maybe_sync()
        model_process_end = datetime.datetime.now()
    else:
        # reuse cached model
        model_download_begin = model_download_end = datetime.datetime.now()
        model_process_begin = model_process_end = model_download_begin

    # -------- preprocess + inference on GPU (with proper sync) --------
    input_image = Image.open(image_path).convert("RGB")
    preprocess = transforms.Compose(
        [
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ]
    )
    input_tensor = preprocess(input_image).unsqueeze(0)  # [1,3,224,224]

    _maybe_sync()
    process_begin = datetime.datetime.now()
    with torch.inference_mode():
        x = input_tensor.to(DEVICE, non_blocking=True)
        if USE_AMP and DEVICE.type == "cuda":
            with torch.cuda.amp.autocast():
                y = model(x)
        else:
            y = model(x)
    _maybe_sync()
    process_end = datetime.datetime.now()

    # -------- postprocess --------
    probs = torch.softmax(y[0], dim=0)
    idx = int(torch.argmax(probs).item())
    pred = idx2label[idx]

    # -------- SAME measurement keys (microseconds) --------
    download_time = (image_download_end - image_download_begin) / datetime.timedelta(microseconds=1)
    model_download_time = (model_download_end - model_download_begin) / datetime.timedelta(
        microseconds=1
    )
    model_process_time = (model_process_end - model_process_begin) / datetime.timedelta(
        microseconds=1
    )
    process_time = (process_end - process_begin) / datetime.timedelta(microseconds=1)

    return {
        "result": {"idx": idx, "class": pred},
        "measurement": {
            "download_time": download_time + model_download_time,
            "compute_time": process_time + model_process_time,
            "model_time": model_process_time,
            "model_download_time": model_download_time,
        },
    }
