# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

size_generators = {
    'test' : 10,
    'small' : 1000,
    'large': 100000
}

def generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_func, nosql_func):
    input_config = {'username': 'testname'} 
    input_config['random_len'] = size_generators[size]
    return input_config

def validate_output(input_config: dict, output: dict, language: str, storage = None) -> str | None:
    result = output.get('output', '')
    username = input_config.get('username', '')
    random_len = input_config.get('random_len', 0)

    if not isinstance(result, str) or len(result) == 0:
        return f"Output is not a non-empty string (type={type(result).__name__}, len={len(result) if isinstance(result, str) else 'N/A'})"

    if f'Welcome {username}!' not in result:
        return f"Missing expected username greeting 'Welcome {username}!' in HTML output"

    if 'Data generated at:' not in result:
        return "Missing expected timestamp text 'Data generated at:' in HTML output"

    actual_li_count = result.count('<li>')
    if actual_li_count != random_len:
        return f"Expected {random_len} list items but found {actual_li_count} <li> tags in HTML output"

    return None
