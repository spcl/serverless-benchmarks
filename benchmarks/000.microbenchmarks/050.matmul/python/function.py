#!/usr/bin/env python3
import torch
import datetime


def initialize_torch(NI, NJ, NK, dtype=torch.float32, device="cuda"):
    alpha = torch.tensor(1.5, dtype=dtype, device=device)
    beta = torch.tensor(1.2, dtype=dtype, device=device)
    i = torch.arange(NI, device=device)
    j = torch.arange(NJ, device=device)
    k = torch.arange(NK, device=device)
    C = ((i[:, None] * j[None, :] + 1) % NI).to(dtype) / NI
    A = ((i[:, None] * (k[None, :] + 1)) % NK).to(dtype) / NK
    B = ((k[:, None] * (j[None, :] + 2)) % NJ).to(dtype) / NJ
    return alpha, beta, C, A, B


def kernel_gemm(alpha, beta, C, A, B, reps):
    torch.cuda.synchronize()
    _ = alpha * (A @ B) + beta * C  # warmup
    torch.cuda.synchronize()
    start = torch.cuda.Event(enable_timing=True)
    end = torch.cuda.Event(enable_timing=True)
    start.record()
    for _ in range(reps):
        C = alpha * (A @ B) + beta * C
    end.record()
    torch.cuda.synchronize()
    return C, float(start.elapsed_time(end))  # ms for all reps


def handler(event):

    size = event.get("size")
    reps = event.get("reps")
    if "seed" in event:
        import random

        random.seed(event["seed"])

        seed = event.get("seed")
        seed = int(seed)

    matrix_generating_begin = datetime.datetime.now()
    alpha, beta, C, A, B = initialize_torch(size, size, size, dtype=torch.float32, device="cuda")
    matrix_generating_end = datetime.datetime.now()

    # matmul_begin = datetime.datetime.now()
    C_out, gpu_ms = kernel_gemm(alpha, beta, C, A, B, reps=reps)
    # matmul_end = datetime.datetime.now()

    matrix_generating_time = (matrix_generating_end - matrix_generating_begin) / datetime.timedelta(
        microseconds=1
    )
    # matmul_time = (matmul_end - matmul_begin) / datetime.timedelta(microseconds=1)

    return {
        "result": C_out,
        "measurement": {
            "generating_time": f"{matrix_generating_time} microseconds",
            "compute_time": f"{gpu_ms} milliseconds",
            "avg_compute_time": f"{gpu_ms / reps} milliseconds",
        },
    }
