# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

    #threads-duration
size_generators = {
    'test' : (2, 2),
    'small': (16, 20),
    'large': (50, 2),
    '2-1': (2, 1),
    '4-1': (4, 1),
    '8-1': (8, 1),
    '16-1': (16, 1),
    '2-5': (2, 5),
    '4-5': (4, 5),
    '8-5': (8, 5),
    '16-5': (16, 5),
    '2-10': (2, 10),
    '4-10': (4, 10),
    '8-10': (8, 10),
    '16-10': (16, 10),
    '2-15': (2, 15),
    '4-15': (4, 15),
    '8-15': (8, 15),
    '16-15': (16, 15),
    '2-20': (2, 20),
    '4-20': (4, 20),
    '8-20': (8, 20),
    '16-20': (16, 20),
    '50-1': (50, 1)
}

def buckets_count():
    return (0, 0)

def generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_func, nosql_func):
    count, sleep = size_generators[size]
    return { 'count': count, 'sleep': sleep }


def validate_output(data_dir: str | None, input_config: dict, output: dict, language: str, storage = None) -> str | None:
    if output is None:
        return "Output is None"

    expected_count = input_config['count']

    if not isinstance(output, dict) or "buffer" not in output:
        return f"Expected output dict with 'buffer' key, got: {output!r}"

    results = output["buffer"]
    if not isinstance(results, list):
        return f"Expected 'buffer' to be a list, got {type(results).__name__}"

    if len(results) != expected_count:
        return f"Expected {expected_count} results, got {len(results)}"

    for i, item in enumerate(results):
        if item != "ok":
            return f"Expected element {i} to be 'ok', got {item!r}"

    return None
