import sys, json, math, torch
import datetime


def initialize_torch(N, dtype=torch.int32, device="cuda", seed=42):
    if seed is not None:
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)

    i, j = torch.meshgrid(
        torch.arange(N, device=device), torch.arange(N, device=device), indexing="ij"
    )
    path = ((i * j) % 7 + 1).to(dtype)

    mask = ((i + j) % 13 == 0) | ((i + j) % 7 == 0) | ((i + j) % 11 == 0)
    path = path.masked_fill(mask, torch.as_tensor(999, dtype=dtype, device=device))
    return path


def kernel_fw(path):
    torch.cuda.synchronize()
    path2 = path.clone()
    n = path2.size(0)
    for k in range(n):
        for i in range(n):
            path2[i, :] = torch.minimum(path2[i, :], path2[i, k] + path2[k, :])  # warmup
    torch.cuda.synchronize()

    start_evt = torch.cuda.Event(enable_timing=True)
    end_evt = torch.cuda.Event(enable_timing=True)
    start_evt.record()
    n = path.size(0)
    for k in range(n):
        for i in range(n):
            path[i, :] = torch.minimum(path[i, :], path[i, k] + path[k, :])
    end_evt.record()
    torch.cuda.synchronize()
    gpu_ms = float(start_evt.elapsed_time(end_evt))
    return path, gpu_ms


def handler(event):
    size = event.get("size")

    if "seed" in event:
        import random

        random.seed(event["seed"])
        seed = event.get("seed", 42)
        seed = int(seed)
    else:
        seed = 42

    gen_begin = datetime.datetime.now()
    path = initialize_torch(size, dtype=torch.float32, device="cuda", seed=seed)
    gen_end = datetime.datetime.now()

    comp_begin = datetime.datetime.now()
    path_out, gpu_ms = kernel_fw(path)
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
