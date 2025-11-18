#!/usr/bin/env python3
import torch
import datetime


def initialize_torch(N, dtype=torch.float32, device="cuda", seed=42):
    if seed is not None:
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
    alpha = torch.randn((), dtype=dtype, device=device)
    x = torch.randn(N, dtype=dtype, device=device)
    y = torch.randn(N, dtype=dtype, device=device)
    return alpha, x, y


def kernel_axpy(alpha, x, y, reps=100):
    torch.cuda.synchronize()
    _ = alpha * x + y  # warmup
    torch.cuda.synchronize()

    start_evt = torch.cuda.Event(enable_timing=True)
    end_evt = torch.cuda.Event(enable_timing=True)
    start_evt.record()
    for _ in range(reps):
        y = alpha * x + y
    end_evt.record()
    torch.cuda.synchronize()
    gpu_ms = float(start_evt.elapsed_time(end_evt))
    return y, gpu_ms


def handler(event):
    size = event.get("size")
    if "seed" in event:
        import random

        random.seed(event["seed"])

        seed = event.get("seed", 42)
        seed = int(seed)

    gen_begin = datetime.datetime.now()
    alpha, x, y = initialize_torch(size, dtype=torch.float32, device="cuda", seed=seed)
    gen_end = datetime.datetime.now()

    comp_begin = datetime.datetime.now()
    y_out, gpu_ms = kernel_axpy(alpha, x, y, reps=100)
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
