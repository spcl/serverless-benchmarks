#!/usr/bin/env python3
import torch
import datetime


def initialize_torch(size, dtype=torch.float16, device="cuda"):
    A = torch.randn((size, size), dtype=dtype, device=device)
    B = torch.randn((size, size), dtype=dtype, device=device)
    return A, B

def handler(event):

    size = event.get("size", 1000)
    reps = event.get("reps", 100)
    
    if "seed" in event:
        import random
        random.seed(event["seed"])
        seed = event.get("seed")
        seed = int(seed)
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
    
    sync = torch.cuda.synchronize

    matrix_generating_begin = datetime.datetime.now()
    sync()
    A, B = initialize_torch(size, dtype=torch.float16, device="cuda")
    sync()
    matrix_generating_end = datetime.datetime.now()

    # Warm up
    for _ in range(10):
        _ = torch.matmul(A, B)

    matmul_begin = datetime.datetime.now()
    sync()
    for _ in range(reps):
        _ = torch.matmul(A, B)
    sync()
    matmul_end = datetime.datetime.now()

    matrix_generating_time = (matrix_generating_end - matrix_generating_begin) / datetime.timedelta(
        microseconds=1
    )
    matmul_time = (matmul_end - matmul_begin) / datetime.timedelta(microseconds=1)
    num_flops = 2 * (size**3) * reps

    return {
        "size": size,
        "reps": reps,
        "measurement": {
            "matrix_generating_time_us": f"{matrix_generating_time} microseconds",
            "compute_time_us": f"{matmul_time} microseconds",
            "avg_compute_time_us": f"{matmul_time / reps} microseconds",
            "Total flops": f"{num_flops} FLOPs",
            "avg TeraFLOPS per second": f"{(num_flops) / (matmul_time * 1e6)} TFLOPS/s",
        },
    }
