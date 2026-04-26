# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

size_generators = {
    'test' : 1,
    'small' : 100,
    'large': 1000
}

def buckets_count():
    return (0, 0)

def generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_func, nosql_func):
    return { 'sleep': size_generators[size] }

def validate_output(data_dir: str | None, input_config: dict, output: dict, language: str, storage = None) -> str | None:

    if output.get('result') != input_config.get('sleep'):
        return f"Expected sleep duration {input_config.get('sleep')} but got {output.get('result')}"

    return None
