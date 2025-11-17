size_generators = {
    "test": {"M": 2000, "N": 2000},
    "small": {"M": 5000, "N": 5000},
    "large": {"M": 16000, "N": 16000},
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
    return {"size": size_generators[size]}
