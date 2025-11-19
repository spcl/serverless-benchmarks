# benchmarks/gpu_cache_latency/handler.py

import json
import subprocess

def handler(event, context=None):
    working_set_kb = int(event["working_set_kb"])
    pattern = event["pattern"]
    iterations = int(event["iterations"])

    ws_bytes = working_set_kb * 1024

    result = subprocess.check_output(
        [
            "./gpu_cache_bench",
            str(ws_bytes),
            pattern,
            str(iterations),
        ],
        text=True,
    )

    metrics = json.loads(result)
    metrics.update(
        {
            "working_set_kb": working_set_kb,
            "pattern": pattern,
            "iterations": iterations,
        }
    )
    return metrics
