# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

size_generators = {
    'test' : 100,
    'small': 5000,
    'large': 10000,
}

def buckets_count():
    return (0, 0)

def generate_input(data_dir, size, benchmarks_bucket, input_buckets, output_buckets, upload_func, nosql_func):
    num_samples = size_generators[size]
    return { 'num_samples': num_samples }

def validate_output(data_dir: str | None, input_config: dict, output: dict, language: str, storage = None) -> str | None:
    if output is None:
        return "Output is None"

    if output != "ok":
        return f"Expected output to be exactly 'ok', got: {output!r}"

    return None
