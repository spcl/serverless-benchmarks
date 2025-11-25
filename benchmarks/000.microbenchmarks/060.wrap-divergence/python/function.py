import json
import time
from typing import List, Dict, Any

import torch


def heavy_work(x: torch.Tensor, iters: int) -> torch.Tensor:
    """
    Simple compute-heavy loop: about 2 FLOPs per element per iteration.
    """
    for _ in range(iters):
        x = x * 1.000001 + 1.0
    return x


def run_one_case(
    num_warps: int,
    iters: int,
    active_lanes: int,
    device: torch.device,
) -> float:
    """
    Run one configuration with a given number of active lanes per 'warp'.
    Returns elapsed time in milliseconds.
    """
    warp_size = 32
    n = num_warps * warp_size

    # lane_id: 0..31 repeated for each warp
    lane_ids = torch.arange(warp_size, device=device).repeat(num_warps)

    # Boolean mask for "active" lanes
    mask = lane_ids < active_lanes

    # Data tensor
    x = torch.ones(n, device=device)

    if device.type == "cuda":
        torch.cuda.synchronize()
    t0 = time.perf_counter()

    # Only active lanes do heavy work; inactive lanes do almost nothing
    x_active = x[mask]
    if active_lanes > 0:
        x_active = heavy_work(x_active, iters)
    x[mask] = x_active

    if device.type == "cuda":
        torch.cuda.synchronize()
    t1 = time.perf_counter()

    # Prevent optimization away
    _ = x.sum().item()

    return (t1 - t0) * 1e3  # ms


def run_benchmark(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Core benchmark logic used by handler().
    """
    num_warps = int(config["num_warps"])
    iters = int(config["iters"])
    active_lanes_list: List[int] = [int(x) for x in config["active_lanes"]]

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    results = []
    for active_lanes in active_lanes_list:
        time_ms = run_one_case(num_warps, iters, active_lanes, device)

        # Useful FLOPs: only active lanes count
        active_threads = num_warps * active_lanes
        flops = 2.0 * iters * active_threads  # 2 FLOPs per iter
        gflops = flops / (time_ms * 1e6) if time_ms > 0 else 0.0

        results.append(
            {
                "active_lanes": active_lanes,
                "time_ms": time_ms,
                "gflops_effective": gflops,
            }
        )

    return {
        "num_warps": num_warps,
        "iters": iters,
        "device": str(device),
        "results": results,
    }


def handler(event, context=None):
    """
    Entry point used by SeBS local backend for Python.

    The event is the JSON config uploaded by input.py:
      {
        "num_warps": ...,
        "iters": ...,
        "active_lanes": [...]
      }
    """
    if isinstance(event, str):
        event = json.loads(event)

    if isinstance(event, dict) and "config" in event and isinstance(event["config"], dict):
        config = event["config"]
    else:
        config = event

    return run_benchmark(config)
