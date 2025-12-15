import datetime
import json
import os
import uuid

import torch
import torch.nn as nn

from . import storage

client = storage.storage.get_instance()

MODEL_FILE = "dlrm_tiny.pt"
MODEL_CACHE = "/tmp/dlrm_gpu_model"

_model = None
_device = torch.device("cpu")


class TinyDLRM(nn.Module):
    def __init__(self, num_users, num_items, num_categories, embed_dim=8):
        super().__init__()
        self.user_emb = nn.Embedding(num_users, embed_dim)
        self.item_emb = nn.Embedding(num_items, embed_dim)
        self.category_emb = nn.Embedding(num_categories, embed_dim)
        in_dim = embed_dim * 3 + 2
        hidden = 16
        self.mlp = nn.Sequential(
            nn.Linear(in_dim, hidden),
            nn.ReLU(),
            nn.Linear(hidden, 1),
        )

    def forward(self, user_id, item_id, category_id, dense):
        features = torch.cat(
            [
                self.user_emb(user_id),
                self.item_emb(item_id),
                self.category_emb(category_id),
                dense,
            ],
            dim=-1,
        )
        return torch.sigmoid(self.mlp(features))


def _select_device():
    if torch.cuda.is_available():
        return torch.device("cuda")
    raise RuntimeError("CUDA is not available")
    return torch.device("cpu")


def _load_model(bucket, prefix):
    global _model, _device

    if _model is not None:
        return 0.0, 0.0

    download_begin = datetime.datetime.now()
    os.makedirs(MODEL_CACHE, exist_ok=True)
    tmp_path = os.path.join("/tmp", f"{uuid.uuid4()}-{MODEL_FILE}")
    client.download(bucket, os.path.join(prefix, MODEL_FILE), tmp_path)
    download_end = datetime.datetime.now()

    process_begin = datetime.datetime.now()
    checkpoint = torch.load(tmp_path, map_location="cpu")
    meta = checkpoint["meta"]
    _device = _select_device()
    model = TinyDLRM(
        meta["num_users"], meta["num_items"], meta["num_categories"], meta["embed_dim"]
    )
    model.load_state_dict(checkpoint["state_dict"])
    model.to(_device)
    model.eval()
    _model = model
    os.remove(tmp_path)
    process_end = datetime.datetime.now()

    download_time = (download_end - download_begin) / datetime.timedelta(microseconds=1)
    process_time = (process_end - process_begin) / datetime.timedelta(microseconds=1)
    return download_time, process_time


def _prepare_batch(requests):
    user_ids = torch.tensor(
        [req["user_id"] for req in requests], dtype=torch.long, device=_device
    )
    item_ids = torch.tensor(
        [req["item_id"] for req in requests], dtype=torch.long, device=_device
    )
    category_ids = torch.tensor(
        [req["category_id"] for req in requests], dtype=torch.long, device=_device
    )
    dense = torch.tensor(
        [req.get("dense", [0.0, 0.0]) for req in requests],
        dtype=torch.float32,
        device=_device,
    )
    return user_ids, item_ids, category_ids, dense


def handler(event):
    bucket = event.get("bucket", {}).get("bucket")
    model_prefix = event.get("bucket", {}).get("model")
    requests_prefix = event.get("bucket", {}).get("requests")
    requests_key = event.get("object", {}).get("requests")

    download_begin = datetime.datetime.now()
    req_path = os.path.join("/tmp", f"{uuid.uuid4()}-{os.path.basename(requests_key)}")
    client.download(bucket, os.path.join(requests_prefix, requests_key), req_path)
    download_end = datetime.datetime.now()

    model_download_time, model_process_time = _load_model(bucket, model_prefix)

    with open(req_path, "r") as f:
        payloads = [json.loads(line) for line in f if line.strip()]
    os.remove(req_path)

    inference_begin = datetime.datetime.now()
    user_ids, item_ids, category_ids, dense = _prepare_batch(payloads)

    with torch.no_grad():
        scores = _model(user_ids, item_ids, category_ids, dense).squeeze(-1).tolist()
    inference_end = datetime.datetime.now()

    predictions = []
    for req, score in zip(payloads, scores):
        predictions.append(
            {
                "user_id": req["user_id"],
                "item_id": req["item_id"],
                "category_id": req["category_id"],
                "score": score,
                "device": str(_device),
            }
        )

    download_time = (download_end - download_begin) / datetime.timedelta(microseconds=1)
    compute_time = (inference_end - inference_begin) / datetime.timedelta(
        microseconds=1
    )

    return {
        "result": {"predictions": predictions},
        "measurement": {
            "download_time": download_time + model_download_time,
            "compute_time": compute_time + model_process_time,
            "model_time": model_process_time,
            "model_download_time": model_download_time,
        },
    }
