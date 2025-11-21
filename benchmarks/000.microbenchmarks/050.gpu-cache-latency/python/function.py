# benchmarks/000.microbenchmarks/050.gpu-cache-latency/python/function.py

import time
import math
import torch


def build_next_indices(n: int, pattern: str, device: torch.device, seed: int = 42):
    """
    Build the 'next' array with the given pattern, similar to your C++ version.
    """
    if n <= 0:
        n = 1

    idx = torch.empty(n, dtype=torch.long)

    if pattern == "sequential":
        idx = (torch.arange(n, dtype=torch.long) + 1) % n
    elif pattern.startswith("stride_"):
        stride = int(pattern.split("_", 1)[1])
        idx = (torch.arange(n, dtype=torch.long) + stride) % n
    elif pattern == "random":
        # deterministic permutation
        g = torch.Generator()
        g.manual_seed(seed)
        perm = torch.randperm(n, generator=g)
        idx[perm] = perm.roll(-1)
    else:
        raise ValueError(f"Unknown pattern '{pattern}'")

    return idx.to(device)


def pointer_chase(working_set_bytes: int, pattern: str, iterations: int, seed: int = 42):
    """
    Pointer-chase microbenchmark, implemented in PyTorch.
    Uses GPU if available; otherwise falls back to CPU.
    """

    # Number of ints in the working set
    n = max(1, working_set_bytes // 4)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    next_idx = build_next_indices(n, pattern, device, seed=seed)

    cur = torch.tensor(0, dtype=torch.long, device=device)
    acc = torch.tensor(0, dtype=torch.long, device=device)

    # Warmup (like your C++ version)
    warmup_iters = min(iterations, 1024)
    for _ in range(warmup_iters):
        cur = next_idx[cur]
        acc = acc + cur

    # Measure time
    if device.type == "cuda":
        torch.cuda.synchronize()
        start_event = torch.cuda.Event(enable_timing=True)
        end_event = torch.cuda.Event(enable_timing=True)

        start_event.record()
        for _ in range(iterations):
            cur = next_idx[cur]
            acc = acc + cur
        end_event.record()
        torch.cuda.synchronize()

        elapsed_ms = start_event.elapsed_time(end_event)  # ms
        total_seconds = elapsed_ms / 1000.0
    else:
        start_time = time.perf_counter()
        for _ in range(iterations):
            cur = next_idx[cur]
            acc = acc + cur
        total_seconds = time.perf_counter() - start_time

    avg_ns = (total_seconds * 1e9 / iterations) if iterations > 0 else 0.0

    return {
        "working_set_bytes": int(working_set_bytes),
        "pattern": pattern,
        "iterations": int(iterations),
        "device": str(device),
        "total_seconds": total_seconds,
        "avg_ns_per_step": avg_ns,
        "sink": int(acc.item()),
    }


def handler(event, context=None):
    """
    Entry point for SeBS.

    For Python benchmarks, SeBS passes:
      event = {
        "input": { ...whatever generate_input returned... },
        ...
      }
    We must return: { "result": <anything JSON-serializable> }
    """

    params = event.get("input", {})

    working_set_bytes = int(params.get("working_set_bytes", 1 << 20))
    pattern = params.get("pattern", "random")
    iterations = int(params.get("iterations", 100_000))
    seed = int(params.get("seed", 42))

    result = pointer_chase(working_set_bytes, pattern, iterations, seed=seed)

    # SeBS expects this shape
    return {
        "result": result
    }
