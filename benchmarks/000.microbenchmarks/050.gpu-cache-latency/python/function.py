# benchmarks/000.microbenchmarks/050.gpu-cache-latency/python/function.py

import argparse
import csv
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import torch


def _load_input_module():
    """Import the benchmark's input.py from the benchmark package."""
    try:
        import importlib

        return importlib.import_module("input")
    except ModuleNotFoundError as exc:
        raise RuntimeError("input.py is required to use --size but could not be imported.") from exc


def build_next_indices(n: int, pattern: str, device: torch.device, seed: int = 42) -> torch.Tensor:
    """
    Build the 'next' array (int64 indices) implementing a pointer-chase permutation.
    """
    n = max(1, int(n))

    if pattern == "sequential":
        idx = (torch.arange(n, dtype=torch.long, device=device) + 1) % n
        return idx.contiguous()

    if pattern.startswith("stride_"):
        stride = int(pattern.split("_", 1)[1])
        idx = (torch.arange(n, dtype=torch.long, device=device) + stride) % n
        return idx.contiguous()

    if pattern == "random":
        # Build deterministically on CPU, then move to target device.
        g = torch.Generator(device="cpu")
        g.manual_seed(int(seed))
        perm = torch.randperm(n, generator=g, device="cpu")
        idx_cpu = torch.empty(n, dtype=torch.long, device="cpu")
        idx_cpu[perm] = perm.roll(-1)
        return idx_cpu.to(device).contiguous()

    raise ValueError(f"Unknown pattern '{pattern}'")


def _pointer_chase_torch(next_idx: torch.Tensor, iterations: int) -> torch.Tensor:
    """
    Pointer chase implemented using torch tensor indexing.

    Returns a small tensor [cur, acc] so results depend on the loop
    (prevents dead-code elimination style effects).
    """
    device = next_idx.device
    cur = torch.tensor(0, dtype=torch.long, device=device)
    acc = torch.tensor(0, dtype=torch.long, device=device)

    for _ in range(int(iterations)):
        cur = next_idx[cur]
        acc = acc + cur

    return torch.stack([cur, acc], dim=0)


def pointer_chase(
    working_set_bytes: int,
    pattern: str,
    iterations: int,
    seed: int = 42,
) -> Dict[str, Any]:
    """
    Pointer-chase microbenchmark (JIT-free).

    - Uses CUDA if available; otherwise CPU.
    - Timing uses CUDA events on GPU and perf_counter on CPU.
    - Pure torch indexing loop (no custom extensions / nvcc).
    """
    working_set_bytes = int(working_set_bytes)
    iterations = int(iterations)
    n = max(1, working_set_bytes // 8)  # int64 indices

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    next_idx = build_next_indices(n, pattern, device=device, seed=seed)

    # Warmup: reduce first-use overhead / cache cold-start effects.
    warmup_iters = min(iterations, 1024)
    _ = _pointer_chase_torch(next_idx, warmup_iters)
    if device.type == "cuda":
        torch.cuda.synchronize()

    if device.type == "cuda":
        start = torch.cuda.Event(enable_timing=True)
        end = torch.cuda.Event(enable_timing=True)

        start.record()
        sink = _pointer_chase_torch(next_idx, iterations)
        end.record()

        torch.cuda.synchronize()
        total_seconds = float(start.elapsed_time(end)) / 1000.0
    else:
        t0 = time.perf_counter()
        sink = _pointer_chase_torch(next_idx, iterations)
        total_seconds = time.perf_counter() - t0

    cur_value, acc_value = [int(x) for x in sink.tolist()]
    avg_ns = (total_seconds * 1e9 / iterations) if iterations > 0 else 0.0

    return {
        "working_set_bytes": working_set_bytes,
        "pattern": str(pattern),
        "iterations": iterations,
        "seed": int(seed),
        "device": str(device),
        "total_seconds": float(total_seconds),
        "avg_ns_per_step": float(avg_ns),
        "sink": int(acc_value),
        "cur": int(cur_value),
    }


def _unwrap_event_input(event: Any) -> Dict[str, Any]:
    """
    Make handler compatible with both styles:
      - event is already the input dict
      - event = {"input": {...}, ...}
    """
    if isinstance(event, dict) and isinstance(event.get("input"), dict):
        return event["input"]
    if isinstance(event, dict):
        return event
    return {}


def handler(event, context=None):
    """
    SeBS entry point.
    Returns JSON-serializable payload with both result + basic measurement fields.
    """
    params = _unwrap_event_input(event)

    working_set_bytes = int(params.get("working_set_bytes", 1 << 20))
    pattern = str(params.get("pattern", "random"))
    iterations = int(params.get("iterations", 100_000))
    seed = int(params.get("seed", 42))

    result = pointer_chase(working_set_bytes, pattern, iterations, seed=seed)

    return {
        "result": result,
        "measurement": {
            "total_seconds": result["total_seconds"],
            "avg_ns_per_step": result["avg_ns_per_step"],
        },
    }


# ---------------------------
# Optional local CLI harness
# ---------------------------


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Run the pointer-chase microbenchmark without SeBS."
    )
    parser.add_argument("--working-set-bytes", type=int, default=1 << 20, dest="working_set_bytes")
    parser.add_argument(
        "--pattern",
        action="append",
        dest="patterns",
        default=None,
        help="Access pattern(s): random, sequential, stride_X. Repeat to sweep multiple.",
    )
    parser.add_argument("--iterations", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=42)

    size_choices = _size_choices()
    size_kwargs: Dict[str, Any] = {"dest": "size", "help": "Use preset from input.py (e.g. test)."}
    if size_choices:
        size_kwargs["choices"] = size_choices
        size_kwargs["help"] += f" Choices: {', '.join(size_choices)}."
    parser.add_argument("--size", **size_kwargs)

    parser.add_argument("--batch", action="store_true", help="Run all selected presets.")
    parser.add_argument(
        "--sizes", type=str, help="Comma-separated preset names (e.g. test,small,large)."
    )
    parser.add_argument("--csv", type=str, help="Optional path to write results as CSV.")
    return parser.parse_args()


def _size_choices() -> List[str]:
    try:
        module = _load_input_module()
    except RuntimeError:
        return []
    return sorted(module.size_generators.keys())


def _comma_separated_list(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    return [entry.strip() for entry in raw.split(",") if entry.strip()]


def _pattern_list(patterns_arg: Optional[List[str]]) -> List[str]:
    patterns = patterns_arg or ["random"]
    out: List[str] = []
    for pat in patterns:
        out.extend([p.strip() for p in pat.split(",") if p.strip()])
    return out or ["random"]


def _config_from_size(size: str) -> Dict[str, Any]:
    module = _load_input_module()
    cfg = module.generate_input(None, size, None, None, None, None, None)
    return dict(cfg)


def _augment_result(result: Dict[str, Any], size_label: str) -> Dict[str, Any]:
    total_seconds = float(result["total_seconds"])
    iterations = int(result["iterations"])
    steps_per_second = iterations / total_seconds if total_seconds > 0 else 0.0
    approx_gb_per_s = (iterations * 8) / total_seconds / (1024**3) if total_seconds > 0 else 0.0

    out = dict(result)
    out.update(
        {
            "timestamp": datetime.utcnow().isoformat(),
            "size_label": size_label,
            "steps_per_second": float(steps_per_second),
            "approx_gb_per_s": float(approx_gb_per_s),
        }
    )
    return out


def _write_csv(records: List[Dict[str, Any]], csv_path: str):
    if not records:
        return
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "timestamp",
        "size_label",
        "pattern",
        "working_set_bytes",
        "iterations",
        "seed",
        "device",
        "total_seconds",
        "avg_ns_per_step",
        "steps_per_second",
        "approx_gb_per_s",
        "sink",
        "cur",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in records:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


if __name__ == "__main__":
    args = _parse_args()
    patterns = _pattern_list(args.patterns)

    def run_config(config: Dict[str, Any], size_label: str) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        for pat in patterns:
            cfg = dict(config)
            cfg["pattern"] = pat
            out = pointer_chase(
                working_set_bytes=cfg["working_set_bytes"],
                pattern=cfg["pattern"],
                iterations=cfg["iterations"],
                seed=cfg.get("seed", args.seed),
            )
            rec = _augment_result(out, size_label=size_label)
            records.append(rec)
            print(json.dumps(rec, indent=2))
        return records

    all_records: List[Dict[str, Any]] = []

    if args.batch:
        available = _size_choices()
        selected = _comma_separated_list(args.sizes) if args.sizes else available
        for preset in selected:
            if preset not in available:
                raise ValueError(f"Unknown preset '{preset}'. Available: {', '.join(available)}")
            cfg = _config_from_size(preset)
            all_records.extend(run_config(cfg, size_label=preset))
    else:
        if args.size:
            cfg = _config_from_size(args.size)
            size_label = args.size
        else:
            size_label = "manual"
            cfg = {
                "working_set_bytes": args.working_set_bytes,
                "pattern": patterns[0],
                "iterations": args.iterations,
                "seed": args.seed,
            }
        all_records.extend(run_config(cfg, size_label=size_label))

    if args.csv:
        _write_csv(all_records, args.csv)
