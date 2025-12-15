size_generators = {"test": 1 << 10, "small": 1 << 26, "large": 1 << 29}


def buckets_count():
    return (0, 0)


def generate_input(
    data_dir,
    size,
    benchmarks_bucket,
    input_paths,
    output_paths,
    upload_func,
    nosql_func,
):
    return {"size": size_generators[size]}
