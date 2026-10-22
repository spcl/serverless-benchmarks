"""Prepare a local model snapshot through the existing SeBS storage interface."""
import hashlib
import json
import os
from pathlib import Path
import posixpath
import urllib.request
import fcntl
import logging

TOKEN_LIMITS = {"test": 8, "small": 32, "large": 128}
PROMPT = "Explain what a serverless function is."
DEFAULT_MANIFEST = Path(__file__).with_name("default-model.json")


def default_model():
    """Download pinned input files automatically and reuse verified local files."""
    manifest = json.loads(DEFAULT_MANIFEST.read_text())
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    root = cache / "sebs" / "421.llm-inference" / manifest["revision"]
    root.mkdir(parents=True, exist_ok=True)
    # Serialize concurrent preparations; process exit releases the lock.
    with (root / ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for entry in manifest["files"]:
            target = root / entry["path"]
            if target.is_file() and target.stat().st_size == entry["size"]:
                with target.open("rb") as stream:
                    checksum = hashlib.sha256()
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        checksum.update(chunk)
                    digest = checksum.hexdigest()
                if digest == entry["sha256"]:
                    continue
            logging.getLogger(__name__).info("Downloading model input %s", entry["path"])
            url = (
                f"https://huggingface.co/{manifest['model']}/resolve/"
                f"{manifest['revision']}/{entry['path']}"
            )
            partial = root / ("." + entry["path"] + ".partial")
            try:
                digest = hashlib.sha256()
                with urllib.request.urlopen(url, timeout=120) as response, partial.open(
                    "wb"
                ) as out:
                    for chunk in iter(lambda: response.read(1024 * 1024), b""):
                        digest.update(chunk)
                        out.write(chunk)
                if partial.stat().st_size != entry["size"] or digest.hexdigest() != entry["sha256"]:
                    raise ValueError(f"Model input integrity check failed: {entry['path']}")
                partial.replace(target)
            finally:
                partial.unlink(missing_ok=True)
    return root


def buckets_count():
    """Request one model input prefix and no output prefix."""
    return (1, 0)


def generate_input(
    data_dir,
    size,
    benchmarks_bucket,
    input_paths,
    output_paths,
    upload_func,
    nosql_func,
):
    """Inventory, hash and upload the snapshot; return a self-contained event."""
    if size not in TOKEN_LIMITS:
        raise ValueError(f"Unknown input profile: {size}")
    directory = os.environ.get("SEBS_LLM_MODEL_DIR")
    root = (Path(directory) if directory else default_model()).resolve()
    files = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part.startswith(".") for part in relative.parts) or not path.is_file():
            continue
        if not path.resolve().is_relative_to(root):
            raise ValueError(f"Model file escapes the snapshot: {relative}")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        files.append(
            {
                "path": relative.as_posix(),
                "size": path.stat().st_size,
                "sha256": digest.hexdigest(),
            }
        )
    names = {file["path"] for file in files}
    if "config.json" not in names or not any(name.endswith(".safetensors") for name in names):
        raise ValueError("Model snapshot must contain config.json and safetensors weights")
    model_id = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    prefix = f"models/{model_id}"
    for file in files:
        upload_func(0, posixpath.join(prefix, file["path"]), str(root / file["path"]))
    return {
        "bucket": benchmarks_bucket,
        "model_prefix": posixpath.join(input_paths[0], prefix),
        "model_id": model_id,
        "files": files,
        "prompt": PROMPT,
        "max_tokens": TOKEN_LIMITS[size],
    }


def validate_output(data_dir, input_config, output, language, storage=None):
    """Check generated text, model identity and output token count."""
    result = output.get("result", {})
    text = result.get("text", "")
    if not isinstance(text, str) or not text.strip():
        return "Generated text is empty"
    if result.get("model_id") != input_config["model_id"]:
        return "Wrong model identity"
    output_tokens = output.get("measurement", {}).get("output_tokens", 0)
    if type(output_tokens) is not int or not 0 < output_tokens <= input_config["max_tokens"]:
        return "Output token count must be positive and within the request limit"
    return None
