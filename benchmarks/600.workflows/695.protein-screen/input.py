size_generators = {
    "test": (5, 64, 3),  # 5 candidates, 64 aa each, top 3 returned
    "small": (20, 128, 5),
    "large": (50, 256, 10),
}


def buckets_count():
    # No object storage buckets required for this workflow.
    return (0, 0)


def generate_input(
    data_dir,
    size,
    benchmarks_bucket,
    input_buckets,
    output_buckets,
    upload_func,
    nosql_func,
):
    n_candidates, seq_len, top_k = size_generators[size]
    return {
        "n_candidates": n_candidates,
        "seq_len": seq_len,
        "top_k": top_k,
    }
