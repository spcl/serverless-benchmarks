import datetime
import json
import os
import tarfile
import uuid
from typing import Dict, List, Optional

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from . import storage

client = storage.storage.get_instance()

MODEL_ARCHIVE = "bert-tiny-onnx.tar.gz"
MODEL_DIRECTORY = "/tmp/bert_language_model"
MODEL_SUBDIR = "bert-tiny-onnx"

_session: Optional[ort.InferenceSession] = None
_tokenizer: Optional[Tokenizer] = None
_labels: Optional[Dict[int, str]] = None


def _ensure_model(bucket: str, model_prefix: str):
    """
    Lazily download and initialize the ONNX model and tokenizer.
    """
    global _session, _tokenizer, _labels

    model_path = os.path.join(MODEL_DIRECTORY, MODEL_SUBDIR)
    model_download_begin = datetime.datetime.now()
    model_download_end = model_download_begin

    if _session is None or _tokenizer is None or _labels is None:
        if not os.path.exists(model_path):
            os.makedirs(MODEL_DIRECTORY, exist_ok=True)
            archive_path = os.path.join("/tmp", f"{uuid.uuid4()}-{MODEL_ARCHIVE}")
            client.download(bucket, os.path.join(model_prefix, MODEL_ARCHIVE), archive_path)
            model_download_end = datetime.datetime.now()

            with tarfile.open(archive_path, "r:gz") as tar:
                tar.extractall(MODEL_DIRECTORY)
            os.remove(archive_path)
        else:
            model_download_begin = datetime.datetime.now()
            model_download_end = model_download_begin

        model_process_begin = datetime.datetime.now()
        tokenizer_path = os.path.join(model_path, "tokenizer.json")
        _tokenizer = Tokenizer.from_file(tokenizer_path)
        _tokenizer.enable_truncation(max_length=128)
        _tokenizer.enable_padding(length=128)

        label_map_path = os.path.join(model_path, "label_map.json")
        with open(label_map_path, "r") as f:
            raw_labels = json.load(f)
        _labels = {int(idx): label for idx, label in raw_labels.items()}

        onnx_path = os.path.join(model_path, "model.onnx")
        available_providers = ort.get_available_providers()
        execution_providers = ["CUDAExecutionProvider"] if "CUDAExecutionProvider" in available_providers else []
        execution_providers.append("CPUExecutionProvider")
        # Prefer GPU execution when available, otherwise fall back to CPU.
        _session = ort.InferenceSession(onnx_path, providers=execution_providers)
        model_process_end = datetime.datetime.now()
    else:
        model_process_begin = datetime.datetime.now()
        model_process_end = model_process_begin

    model_download_time = (model_download_end - model_download_begin) / datetime.timedelta(
        microseconds=1
    )
    model_process_time = (model_process_end - model_process_begin) / datetime.timedelta(
        microseconds=1
    )

    return model_download_time, model_process_time


def _prepare_inputs(sentences: List[str]):
    assert _tokenizer is not None

    encodings = _tokenizer.encode_batch(sentences)

    input_ids = np.array([enc.ids for enc in encodings], dtype=np.int64)
    attention_mask = np.array([enc.attention_mask for enc in encodings], dtype=np.int64)
    token_type_ids = np.array(
        [enc.type_ids if enc.type_ids else [0] * len(enc.ids) for enc in encodings],
        dtype=np.int64,
    )

    return {
        "input_ids": input_ids,
        "attention_mask": attention_mask,
        "token_type_ids": token_type_ids,
    }


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits, axis=1, keepdims=True)
    exp = np.exp(shifted)
    return exp / np.sum(exp, axis=1, keepdims=True)


def handler(event):
    bucket = event.get("bucket", {}).get("bucket")
    model_prefix = event.get("bucket", {}).get("model")
    text_prefix = event.get("bucket", {}).get("text")
    text_key = event.get("object", {}).get("input")

    download_begin = datetime.datetime.now()
    text_download_path = os.path.join("/tmp", f"{uuid.uuid4()}-{os.path.basename(text_key)}")
    client.download(bucket, os.path.join(text_prefix, text_key), text_download_path)
    download_end = datetime.datetime.now()

    model_download_time, model_process_time = _ensure_model(bucket, model_prefix)
    assert _session is not None and _labels is not None and _tokenizer is not None

    with open(text_download_path, "r") as f:
        sentences = [json.loads(line)["text"] for line in f if line.strip()]

    os.remove(text_download_path)

    inference_begin = datetime.datetime.now()
    inputs = _prepare_inputs(sentences)
    outputs = _session.run(None, inputs)
    logits = outputs[0]
    probabilities = _softmax(logits)
    inference_end = datetime.datetime.now()

    results = []
    for sentence, probs in zip(sentences, probabilities):
        label_idx = int(np.argmax(probs))
        label = _labels.get(label_idx, str(label_idx))
        results.append(
            {
                "text": sentence,
                "label": label,
                "confidence": float(probs[label_idx]),
                "raw_scores": probs.tolist(),
            }
        )

    download_time = (download_end - download_begin) / datetime.timedelta(microseconds=1)
    compute_time = (inference_end - inference_begin) / datetime.timedelta(microseconds=1)

    return {
        "result": {"predictions": results},
        "measurement": {
            "download_time": download_time + model_download_time,
            "compute_time": compute_time + model_process_time,
            "model_time": model_process_time,
            "model_download_time": model_download_time,
        },
    }
