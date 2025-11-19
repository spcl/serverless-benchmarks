import json
import subprocess
import csv

BINARY = "./gpu_cache_bench"

working_sets = [
    8 * 1024,
    32 * 1024,
    64 * 1024,
    256 * 1024,
    1 * 1024 * 1024,
    4 * 1024 * 1024,
    16 * 1024 * 1024,
]
patterns = ["sequential", "stride_4", "random"]
iters = 1_000_000

with open("cache_latency_results.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["working_set_bytes", "pattern", "iterations",
                     "total_cycles", "avg_cycles", "sink"])
    for ws in working_sets:
        for pattern in patterns:
            print(f"WS={ws} bytes, pattern={pattern} ...", flush=True)
            out = subprocess.check_output(
                [BINARY, str(ws), pattern, str(iters)],
                text=True,
            )
            data = json.loads(out)
            writer.writerow(
                [
                    data["working_set_bytes"],
                    data["pattern"],
                    data["iterations"],
                    data["total_cycles"],
                    data["avg_cycles"],
                    data["sink"],
                ]
            )
