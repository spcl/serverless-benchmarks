# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
import hashlib
import json

size_generators = {
    'test' : 10,
    'small' : 10000,
    'large': 100000
}

# Expected MD5 checksums for deterministic outputs with seed=42
# Format: checksum of JSON-serialized output (full spanning tree edge list)
# MST returns a list of edge indices forming the minimum spanning tree
expected_checksums = {
    10: '2731b0a338d620aac853321b832983c3',
    10000: 'ebac1069ed7b96771ac4a9684bdfc6ba',
    100000: 'b0b868c92d20f96b40c04a0f846f979f',
}

def generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_func, nosql_func):
    return { 'size': size_generators[size], 'seed': 42}

def validate_output(input_config: dict, output: dict, language: str, architecture: str, storage = None) -> str | None:

    result = output.get('result')

    if result is None:
        return "MST result is None"

    size = input_config.get('size')
    seed = input_config.get('seed')

    if seed == 42 and size in expected_checksums:
        serialized = json.dumps(result, separators=(',', ':'))
        actual_checksum = hashlib.md5(serialized.encode()).hexdigest()
        expected_checksum = expected_checksums[size]
        if actual_checksum != expected_checksum:
            return f"MST output checksum mismatch for size={size}: expected '{expected_checksum}' but got '{actual_checksum}'"
    else:
        return f"Unexpected seed={seed} or size={size} for validation."

    return None
