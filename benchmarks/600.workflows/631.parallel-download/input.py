# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

import os
from random import shuffle

size_generators = {
    'test' : (5, 10),
    'small': (20, 2**10),
    'large': (50, 2**10),
    '2e10': (20, 2**10),
    '2e28': (20, 2**28),
    '2e15': (20, 2**15),
    '2e20': (20, 2**20),
    '2e25': (20, 2**25),
    '2e26': (20, 2**26),
    '2e27': (20, 2**27)
}


def buckets_count():
    return (1, 0)


def generate(size):
    elems = list(range(size))
    shuffle(elems)

    length = 0
    for i in elems:
        data = str(i % 255)
        length += len(data)
        if length > size:
            break
        yield data


def generate_input(data_dir, size, benchmarks_bucket, input_buckets, output_buckets, upload_func, nosql_func):
    count, size_bytes = size_generators[size]

    data_name = f"data-{size_bytes}.txt"
    data_path = os.path.join(data_dir, data_name)

    if not os.path.exists(data_path):
        os.makedirs(data_dir, exist_ok=True)
        with open(data_path, "w") as f:
            f.writelines(k for k in generate(size_bytes))

    upload_func(0, data_name, data_path)
    # os.remove(data_path)

    return { 'count': count, "bucket": benchmarks_bucket, "blob": input_buckets[0] + '/' + data_name}


def validate_output(data_dir: str | None, input_config: dict, output: dict, language: str, storage = None) -> str | None:
    expected_count = input_config.get("count")
    if expected_count is None:
        return "Input config missing 'count' field"

    if output is None:
        return "Output is None"

    if not isinstance(output, dict) or "buffer" not in output:
        return f"Expected output dict with 'buffer' key, got: {output!r}"

    results = output["buffer"]
    if not isinstance(results, list):
        return f"Expected 'buffer' to be a list, got {type(results).__name__}"

    if len(results) != expected_count:
        return f"Expected {expected_count} results, got {len(results)}"

    for i, result in enumerate(results):
        if result != "ok":
            return f"Result at index {i} is {result!r}, expected 'ok'"

    return None
