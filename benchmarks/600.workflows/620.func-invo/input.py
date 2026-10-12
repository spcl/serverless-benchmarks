# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

size_generators = {
    'test' : 10,
    'small' : 2**5,
    'large':  2**20,
    '2e5': 2**5,
    '2e8': 2**8,
    '2e10': 2**10,
    '2e12': 2**12,
    '2e14': 2**14,
    '2e16': 2**16,
    '2e18': 2**18,
    '2e18-1000': (2**18)-1000
}

def generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_func, nosql_func):
    return { 'size': size_generators[size] }


def validate_output(data_dir: str | None, input_config: dict, output: dict, language: str, storage = None) -> str | None:
    if output is None:
        return "Output is None"

    if 'len' not in output:
        return "Missing key 'len' in output"

    if not isinstance(output['len'], str):
        return f"Expected 'len' to be a string, got {type(output['len']).__name__}"

    expected_size = input_config['size']
    actual_size = len(output['len'])
    if actual_size != expected_size:
        return f"Expected string length {expected_size}, got {actual_size}"

    # The string is built by concatenating str(i % 255) for shuffled i in range(size).
    # Every character must therefore be a decimal digit.
    s = output['len']
    if not s.isdigit():
        non_digit = next(c for c in s if not c.isdigit())
        return f"Output string contains non-digit character {non_digit!r}; expected only digits 0-9"

    return None
