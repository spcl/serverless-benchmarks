size_generators = {
    "test": { "N": 8, "W": 14, "H": 14, "C1": 32, "C2": 8 },
    "small": { "N": 8, "W": 28, "H": 28, "C1": 64, "C2": 16 },
    "large": { "N": 8, "W": 56, "H": 56, "C1": 128, "C2": 32 },
}

def generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_func, nosql_func):
    return { 'size': size_generators[size] }
 