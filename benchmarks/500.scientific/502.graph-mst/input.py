# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
size_generators = {
    'test' : 10,
    'small' : 10000,
    'large': 100000
}

def generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_func, nosql_func):
    return { 'size': size_generators[size], 'seed': 42}

def validate_output(input_config: dict, output: dict) -> bool:
    result = output.get('result')
    if result is None:
        return False
    # spanning_tree returns a list of edge IDs; result[0] is the first edge
    # index which must be a non-negative integer.
    if isinstance(result, int):
        return result >= 0
    # Older igraph versions may return a Graph object for result[0].
    return True
