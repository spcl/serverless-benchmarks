"""CPU text generation through the standard SeBS handler and storage adapter."""
import hashlib
from pathlib import Path
import shutil
from time import perf_counter_ns

from . import storage


# The model is downloaded to a fixed path in /tmp, which is ephemeral storage on AWS Lambda.
MODEL_DIR = Path("/tmp/sebs-llm-model")

# We reuse the same engine across warm invocations, so we can avoid reloading the model.
_engine = None
_model_id = None


def _verify_file(path, file):
    """Detect truncated or corrupted storage downloads before publishing a model."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if path.stat().st_size != file["size"] or digest.hexdigest() != file["sha256"]:
        raise ValueError(f"Model download integrity check failed: {file['path']}")


def _download_model(event):
    """Download a model from storage to ephemeral local storage, verifying integrity."""
    # Lambda invokes one request at a time per environment. Reclaim staging left
    # by timeouts/process termination, where a Python finally block cannot run.
    staging = MODEL_DIR.with_name(MODEL_DIR.name + ".partial")
    if staging.exists():
        shutil.rmtree(staging)
    marker = MODEL_DIR / ".ready"
    if marker.is_file() and marker.read_text() == event["model_id"]:
        return MODEL_DIR
    if MODEL_DIR.exists():
        shutil.rmtree(MODEL_DIR)
    MODEL_DIR.parent.mkdir(parents=True, exist_ok=True)
    staging.mkdir()
    try:
        client = storage.storage.get_instance()
        for file in event["files"]:
            target = staging / file["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            key = event["model_prefix"].rstrip("/") + "/" + file["path"]
            client.download(event["bucket"], key, str(target))
            _verify_file(target, file)
        (staging / ".ready").write_text(event["model_id"])
        staging.rename(MODEL_DIR)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return MODEL_DIR


def handler(event):
    """Initialize once, then reuse one engine for warm invocations."""
    global _engine, _model_id
    reused = _engine is not None
    if reused and _model_id != event["model_id"]:
        raise ValueError(
            "Model changed in a warm function; redeploy with --update-code --update-storage"
        )
    download_time = init_time = 0.0
    if not reused:
        start = perf_counter_ns()
        model_path = _download_model(event)
        download_time = (perf_counter_ns() - start) / 1000
        start = perf_counter_ns()
        from vllm import LLM

        engine = LLM(
            model=str(model_path),
            dtype="float32",
            max_model_len=2048,
            distributed_executor_backend="uni",
            kv_cache_memory_bytes=256 * 1024 * 1024,
            block_size=32,
        )
        _engine, _model_id = engine, event["model_id"]
        init_time = (perf_counter_ns() - start) / 1000

    from vllm import SamplingParams

    start = perf_counter_ns()
    output = _engine.chat(
        [{"role": "user", "content": event["prompt"]}],
        sampling_params=SamplingParams(max_tokens=event["max_tokens"], temperature=0),
        use_tqdm=False,
    )[0]
    generation_time = (perf_counter_ns() - start) / 1000
    completion = output.outputs[0]
    input_tokens = len(output.prompt_token_ids)
    output_tokens = len(completion.token_ids)
    return {
        "result": {"text": completion.text, "model_id": _model_id},
        "measurement": {
            "download_time": download_time,
            "compute_time": init_time + generation_time,
            "model_download_time": download_time,
            "model_init_time": init_time,
            "generation_time": generation_time,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "tokens_per_second": (input_tokens + output_tokens) * 1e6 / generation_time,
            "model_reused": reused,
        },
    }
