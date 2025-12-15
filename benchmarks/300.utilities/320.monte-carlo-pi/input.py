# benchmarks/000.microbenchmarks/060.monte-carlo-pi/input.py


def buckets_count():
    # No object storage needed for this benchmark.
    return (0, 0)


size_generators = {
    "test": {"total_samples": 1_000_000, "batch_size": 250_000},
    "small": {"total_samples": 10_000_000, "batch_size": 1_000_000},
    "medium": {"total_samples": 50_000_000, "batch_size": 2_000_000},
    "large": {"total_samples": 200_000_000, "batch_size": 5_000_000},
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
        "total_samples": int(cfg["total_samples"]),
        "batch_size": int(cfg["batch_size"]),
        "seed": 42,
        "prefer_gpu": True,
    }
