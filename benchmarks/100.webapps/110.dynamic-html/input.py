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

def validate_output(input_config: dict, output: dict) -> bool:
    result = output.get('output', '')
    username = input_config.get('username', '')
    random_len = input_config.get('random_len', 0)
    if not isinstance(result, str) or len(result) == 0:
        return False
    if f'Welcome {username}!' not in result:
        return False
    if 'Data generated at:' not in result:
        return False
    if result.count('<li>') != random_len:
        return False
    return True
