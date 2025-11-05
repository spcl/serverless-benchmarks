#!/usr/bin/env python3
import sys, json, math, torch
import datetime


def initialize_torch(N, dtype=torch.float32, device="cuda"):
    i = torch.arange(N, device=device, dtype=dtype).view(-1, 1)
    j = torch.arange(N, device=device, dtype=dtype).view(1, -1)

    A = i * (j + 2) / N
    B = i * (j + 3) / N
    return A, B


def kernel_jacobi2d(A, B, iters=50):
    torch.cuda.synchronize()
    # warmup
    if A.shape[0] > 2 and A.shape[1] > 2:
        B_inner = 0.2 * (A[1:-1, 1:-1] + A[1:-1, :-2] + A[1:-1, 2:] + A[2:, 1:-1] + A[:-2, 1:-1])
        B[1:-1, 1:-1].copy_(B_inner)

        A_inner = 0.2 * (B[1:-1, 1:-1] + B[1:-1, :-2] + B[1:-1, 2:] + B[2:, 1:-1] + B[:-2, 1:-1])
        A[1:-1, 1:-1].copy_(A_inner)
    torch.cuda.synchronize()

    start_evt = torch.cuda.Event(enable_timing=True)
    end_evt = torch.cuda.Event(enable_timing=True)
    start_evt.record()
    for _ in range(iters):
        B_inner = 0.2 * (A[1:-1, 1:-1] + A[1:-1, :-2] + A[1:-1, 2:] + A[2:, 1:-1] + A[:-2, 1:-1])
        B[1:-1, 1:-1].copy_(B_inner)

        A_inner = 0.2 * (B[1:-1, 1:-1] + B[1:-1, :-2] + B[1:-1, 2:] + B[2:, 1:-1] + B[:-2, 1:-1])
        A[1:-1, 1:-1].copy_(A_inner)
    end_evt.record()
    torch.cuda.synchronize()
    gpu_ms = float(start_evt.elapsed_time(end_evt))
    return A, B, gpu_ms


def handler(event):

    size = event.get("size")
    if "seed" in event:
        import random

        random.seed(event["seed"])

        seed = event.get("seed", 42)
        seed = int(seed)

    matrix_generating_begin = datetime.datetime.now()
    A, B = initialize_torch(size, dtype=torch.float32, device="cuda")
    matrix_generating_end = datetime.datetime.now()

    matmul_begin = datetime.datetime.now()
    A_out, B_out, gpu_ms = kernel_jacobi2d(A, B, reps=50)
    matmul_end = datetime.datetime.now()

    matrix_generating_time = (matrix_generating_end - matrix_generating_begin) / datetime.timedelta(
        microseconds=1
    )
    matmul_time = (matmul_end - matmul_begin) / datetime.timedelta(microseconds=1)

    return {
        # "result": result[0],
        "measurement": {
            "graph_generating_time": matrix_generating_time,
            "compute_time": matmul_time,
            "gpu_time": gpu_ms,
        },
    }
