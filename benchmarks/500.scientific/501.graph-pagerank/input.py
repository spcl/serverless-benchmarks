# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
size_generators = {
    'test' : 10,
    'small' : 10000,
    'large': 100000
}

# Expected pagerank[0] values for Barabasi(size, 10) graphs with seed=42.
# Computed with igraph using Python's random.seed(42) before graph generation.
expected_pagerank = {
    10: 0.1,
    10000: 0.0012122480931530321,
    100000: 0.0003338443855258904,
}

def generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_func, nosql_func):
    return { 'size': size_generators[size], 'seed': 42}

def validate_output(input_config: dict, output: dict) -> bool:
    result = output.get('result')
    if not (isinstance(result, float) and 0.0 <= result <= 1.0):
        return False
    size = input_config.get('size')
    seed = input_config.get('seed')
    if seed == 42 and size in expected_pagerank:
        expected = expected_pagerank[size]
        if abs(result - expected) > 1e-10:
            return False
    return True
