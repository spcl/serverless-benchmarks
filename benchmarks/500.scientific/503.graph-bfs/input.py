# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
import hashlib
import json

size_generators = {
    'test' : 10,
    'small' : 10000,
    'large': 100000
}

# Expected MD5 checksums for deterministic outputs with seed=42
# Format: checksum of JSON-serialized output (vertex_order, layer_boundaries, parents)
# Python and C++ may produce different results due to algorithm differences
# in input generation.
expected_checksums = {
    'python': {
        10: '1dfb71bebaebcfb1a850f5b81610c2f7',
        10000: '14160bc08930584610005d05cc20989f',
        100000: '55cb168c17d2371637f483c720f29dfd',
    },
    'cpp': {
        10: '1dfb71bebaebcfb1a850f5b81610c2f7',
        10000: 'dcabd8accdf69b6707dc67f0c769cb4c',
        100000: '5a8a1b56acde2fee8bccc1bf19aeddc5',
    }
}

def generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_func, nosql_func):
    return { 'size': size_generators[size], 'seed': 42}

def validate_output(input_config: dict, output: dict, language: str, architecture: str, storage = None) -> str | None:

    result = output.get('result')

    # BFS returns a 3-tuple: (vertex_order, layer_boundaries, parents).
    # After JSON serialisation the tuple becomes a list of 3 lists.
    if not isinstance(result, (list, tuple)):
        return f"BFS result is not a list/tuple (type={type(result).__name__})"

    if len(result) != 3:
        return f"BFS result should have 3 elements (vertex_order, layer_boundaries, parents) but has {len(result)}"

    size = input_config.get('size', 0)

    seed = input_config.get('seed')
    if seed == 42 and size in expected_checksums[language]:

        serialized = json.dumps(result, separators=(',', ':'))
        actual_checksum = hashlib.md5(serialized.encode()).hexdigest()
        expected_checksum = expected_checksums[language][size]
        if actual_checksum != expected_checksum:
            return f"BFS output checksum mismatch for size={size} ({language}): expected '{expected_checksum}' but got '{actual_checksum}'"
    else:
        return f"Unexpected seed={seed} or size={size} for validation."

    return None
