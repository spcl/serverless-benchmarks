# benchmarks/000.microbenchmarks/060.monte-carlo-pi/python/function.py

import time
from typing import Any, Dict, Tuple

import torch


def _unwrap_event_input(event: Any) -> Dict[str, Any]:
    # Compatible with both styles:
    # - event is already the input dict
    # - event = {"input": {...}, ...}
    if isinstance(event, dict) and isinstance(event.get("input"), dict):
        return event["input"]
    if isinstance(event, dict):
        return event
    return {}


def _resolve_device(prefer_gpu: bool) -> torch.device:
    if prefer_gpu and torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def _time_call(device: torch.device, fn) -> Tuple[float, Any]:
    # Returns (seconds, fn_result)
    if device.type == "cuda":
        torch.cuda.synchronize()
        start = torch.cuda.Event(enable_timing=True)
        end = torch.cuda.Event(enable_timing=True)
        start.record()
        out = fn()
        end.record()
        torch.cuda.synchronize()
        seconds = float(start.elapsed_time(end)) / 1000.0
        return seconds, out

    t0 = time.perf_counter()
    out = fn()
    seconds = time.perf_counter() - t0
    return seconds, out


def estimate_pi_torch(
    total_samples: int,
    batch_size: int,
    seed: int,
    prefer_gpu: bool,
) -> Dict[str, Any]:
    total_samples = int(total_samples)
    batch_size = int(batch_size)
    seed = int(seed)

    if total_samples <= 0:
        raise ValueError("total_samples must be > 0")
    if batch_size <= 0:
        raise ValueError("batch_size must be > 0")

    device = _resolve_device(prefer_gpu)

    # Seed deterministically (good for reproducibility / debugging)
    torch.manual_seed(seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(seed)

    def run():
        hits = torch.zeros((), dtype=torch.int64, device=device)
        remaining = total_samples

        while remaining > 0:
            cur = min(batch_size, remaining)

            # Uniform samples in [0, 1)
            xy = torch.rand((cur, 2), device=device)
            r2 = xy[:, 0] * xy[:, 0] + xy[:, 1] * xy[:, 1]
            hits = hits + (r2 <= 1.0).sum(dtype=torch.int64)

            remaining -= cur

        return int(hits.item())

    compute_seconds, hits = _time_call(device, run)
    pi_est = 4.0 * float(hits) / float(total_samples)
    samples_per_s = float(total_samples) / compute_seconds if compute_seconds > 0 else 0.0

    return {
        "pi_estimate": pi_est,
        "hits": int(hits),
        "samples": int(total_samples),
        "batch_size": int(batch_size),
        "device": str(device),
        "compute_seconds": float(compute_seconds),
        "samples_per_second": float(samples_per_s),
    }


def handler(event, context=None):
    params = _unwrap_event_input(event)

    total_samples = int(params.get("total_samples", 10_000_000))
    batch_size = int(params.get("batch_size", 1_000_000))
    seed = int(params.get("seed", 42))
    prefer_gpu = bool(params.get("prefer_gpu", True))

    result = estimate_pi_torch(total_samples, batch_size, seed, prefer_gpu)

    return {
        "result": result,
        "measurement": {
            "compute_time": result["compute_seconds"] * 1e6,  # microseconds
        },
    }
