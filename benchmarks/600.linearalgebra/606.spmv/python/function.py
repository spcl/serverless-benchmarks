import sys, json, math, torch
import datetime


def initialize_torch(N, density=0.01, dtype=torch.float32, device="cuda", seed=42):
    if seed is not None:
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
    
    nnz = int(N * N * density)
    row_indices = torch.randint(0, N, (nnz,), device=device)
    col_indices = torch.randint(0, N, (nnz,), device=device)
    values = torch.randn(nnz, dtype=dtype, device=device)
    
    indices = torch.stack([row_indices, col_indices])
    sparse_matrix = torch.sparse_coo_tensor(indices, values, (N, N), dtype=dtype, device=device)
    
    sparse_matrix_csr = sparse_matrix.to_sparse_csr()
    
    x = torch.randn(N, dtype=dtype, device=device)
    
    return sparse_matrix_csr, x


def kernel_spmv(A, x, reps=100):
    torch.cuda.synchronize()
    _ = torch.sparse.mm(A, x.unsqueeze(1)).squeeze()  # warmup
    torch.cuda.synchronize()
    
    start_evt = torch.cuda.Event(enable_timing=True)
    end_evt = torch.cuda.Event(enable_timing=True)
    start_evt.record()
    for _ in range(reps):
        y = torch.sparse.mm(A, x.unsqueeze(1)).squeeze()
    end_evt.record()
    torch.cuda.synchronize()
    gpu_ms = float(start_evt.elapsed_time(end_evt))
    return y, gpu_ms


def handler(event):
    size = event.get("size")
    density = event.get("density", 0.01)  # default 1% density
    
    if "seed" in event:
        import random
        random.seed(event["seed"])
        seed = event.get("seed", 42)
        seed = int(seed)
    else:
        seed = 42
    
    gen_begin = datetime.datetime.now()
    A, x = initialize_torch(size, density=density, dtype=torch.float32, device="cuda", seed=seed)
    gen_end = datetime.datetime.now()
    
    comp_begin = datetime.datetime.now()
    y_out, gpu_ms = kernel_spmv(A, x, reps=100)
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
