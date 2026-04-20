# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

size_generators = {
    'test' : 10,
    'small' : 10000,
    'large': 100000
}

# Expected pagerank[0] values for Barabasi(size, 10) graphs with seed=42.
# Computed with igraph using Python's random.seed(42) before graph generation.
# Note: Values may vary slightly due to floating-point precision and igraph version differences
expected_pagerank = {
    "python": {
        10: 0.1,
        10000: 0.00121224809,
        100000: 0.00033384438552589015,
    },
    "cpp": {
        10: 0.1,
        10000: 0.0011396482039798725,
        100000: 0.0003105243690874958,
    },
}

def generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_func, nosql_func):
    return { 'size': size_generators[size], 'seed': 42}

def validate_output(input_config: dict, output: dict, language: str, storage = None) -> str | None:

    result = output.get('output')

    if not isinstance(result, (float, int)):
        return f"PageRank result is not a number (type={type(result).__name__})"

    result = float(result)
    size = input_config.get('size')
    seed = input_config.get('seed')

    expected_result = expected_pagerank[language]

    # Verify value match with tolerance for known seeds
    # PageRank values may have small floating-point variations, so we use tolerance-based checking
    # rather than exact checksums
    if seed == 42 and size in expected_result:
        expected = expected_result[size]
        tolerance = 1e-9
        diff = abs(result - expected)
        if diff > tolerance:
            return f"PageRank result mismatch for size={size}: expected {expected} but got {result} (diff={diff}, tolerance={tolerance})"
    else:
        return f"Unexpected seed={seed} or size={size} for validation."

    return None
