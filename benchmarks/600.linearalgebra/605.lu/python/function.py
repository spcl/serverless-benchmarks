#!/usr/bin/env python3
import torch
import datetime


def initialize_torch(N, dtype=torch.float32, device="cuda"):
    col = torch.arange(N, device=device)
    base = (torch.remainder(-col, N).to(dtype) / N) + 1

    A = torch.tril(base.expand(N, N)).clone()

    A.fill_diagonal_(torch.tensor(1.0, dtype=dtype, device=device))

    A = A @ A.T
    return A


def _kernel_lu(B: torch.Tensor) -> torch.Tensor:
    n = B.shape[0]
    for i in range(n):
        for j in range(i):
            B[i, j] = B[i, j] - (B[i, :j] @ B[:j, j])
            B[i, j] = B[i, j] / B[j, j]
        for j in range(i, n):
            B[i, j] = B[i, j] - (B[i, :i] @ B[:i, j])
    return B


def kernel(A: torch.Tensor):
    torch.cuda.synchronize()

    _ = _kernel_lu(A.clone())  # Warm-up

    torch.cuda.synchronize()

    start_evt = torch.cuda.Event(enable_timing=True)
    end_evt = torch.cuda.Event(enable_timing=True)

    start_evt.record()
    B = None
    for _ in range(A.size(0)):
        B = _kernel_lu(A.clone())
    end_evt.record()

    torch.cuda.synchronize()

    gpu_ms = float(start_evt.elapsed_time(end_evt))
    return B, gpu_ms


def handler(event):
    size = event.get("size")
    if "seed" in event:
        import random

        random.seed(event["seed"])

        seed = event.get("seed", 42)
        seed = int(seed)

    gen_begin = datetime.datetime.now()
    A = initialize_torch(size, dtype=torch.float32, device="cuda")
    gen_end = datetime.datetime.now()

    comp_begin = datetime.datetime.now()
    B, gpu_ms = kernel(A)
    comp_end = datetime.datetime.now()

    gen_us = (gen_end - gen_begin) / datetime.timedelta(microseconds=1)
    comp_us = (comp_end - comp_begin) / datetime.timedelta(microseconds=1)

    return {
        "measurement": {
            "generating_time": gen_us,
            "compute_time": comp_us,
            "gpu_time": gpu_ms,
        }
    }
