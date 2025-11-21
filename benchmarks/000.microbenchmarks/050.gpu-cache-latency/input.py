# benchmarks/000.microbenchmarks/050.gpu-cache-latency/input.py

# You can tune these as you like later
size_generators = {
    "test":   {"working_set_bytes": 1 << 16, "iterations": 10_000},
    "small":  {"working_set_bytes": 1 << 20, "iterations": 100_000},
    "large":  {"working_set_bytes": 1 << 24, "iterations": 1_000_000},
}

def generate_input(
    data_dir,              # path to benchmark data dir (unused here)
    size,                  # "test" | "small" | "large"
    benchmarks_bucket,     # storage bucket (unused locally)
    input_paths,           # list of input paths (unused here)
    output_paths,          # list of output paths (unused here)
    upload_func,           # function to upload data (unused here)
    nosql_func             # function to access NoSQL (unused here)
):
    """
    SeBS calls this to get the JSON-like dict that becomes event['input']
    for the function.
    """
    cfg = size_generators[size]

    return {
        "working_set_bytes": cfg["working_set_bytes"],
        "pattern": "random",      # or "sequential", "stride_4", etc.
        "iterations": cfg["iterations"],
        "seed": 42
    }
