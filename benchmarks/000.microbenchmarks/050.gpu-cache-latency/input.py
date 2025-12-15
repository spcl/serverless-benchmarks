# benchmarks/000.microbenchmarks/050.gpu-cache-latency/input.py


# No object storage needed for this benchmark.
def buckets_count():
    return (0, 0)


# Presets used by `--size` and by SeBS generate_input(size=...)
size_generators = {
    "l1_4kb": {"working_set_bytes": 1 << 12, "iterations": 50_000},
    "l1_16kb": {"working_set_bytes": 1 << 14, "iterations": 50_000},
    "l2_256kb": {"working_set_bytes": 1 << 18, "iterations": 100_000},
    "l2_1mb": {"working_set_bytes": 1 << 20, "iterations": 150_000},
    "l2_2mb": {"working_set_bytes": 2 << 20, "iterations": 200_000},
    "dram_4mb": {"working_set_bytes": 4 << 20, "iterations": 200_000},
    "dram_16mb": {"working_set_bytes": 16 << 20, "iterations": 400_000},
    "dram_32mb": {"working_set_bytes": 32 << 20, "iterations": 500_000},
    "dram_64mb": {"working_set_bytes": 64 << 20, "iterations": 800_000},
    "dram_128mb": {"working_set_bytes": 128 << 20, "iterations": 1_000_000},
    "dram_256mb": {"working_set_bytes": 256 << 20, "iterations": 1_500_000},
    "dram_512mb": {"working_set_bytes": 512 << 20, "iterations": 2_000_000},
    "test": {"working_set_bytes": 1 << 16, "iterations": 10_000},
    "small": {"working_set_bytes": 1 << 20, "iterations": 100_000},
    "large": {"working_set_bytes": 1 << 24, "iterations": 1_000_000},
}


def generate_input(
    data_dir,
    size,
    benchmarks_bucket,
    input_paths,
    output_paths,
    upload_func,
    nosql_func,
):
    cfg = size_generators[size]
    return {
        "working_set_bytes": int(cfg["working_set_bytes"]),
        "pattern": "random",
        "iterations": int(cfg["iterations"]),
        "seed": 42,
    }
