# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
size_generators = {
    'test' : 10,
    'small' : 10000,
    'large': 100000
}

def generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_func, nosql_func):
    return { 'size': size_generators[size], 'seed': 42}

def validate_output(input_config: dict, output: dict) -> bool:
    result = output.get('result')
    # BFS returns a 3-tuple: (vertex_order, layer_boundaries, parents).
    # After JSON serialisation the tuple becomes a list of 3 lists.
    if not (isinstance(result, (list, tuple)) and len(result) == 3):
        return False
    vertex_order = result[0]
    size = input_config.get('size', 0)
    # Every vertex in a connected graph must be visited exactly once.
    if not (isinstance(vertex_order, (list, tuple)) and len(vertex_order) == size):
        return False
    # BFS from vertex 0 must start at vertex 0.
    if vertex_order[0] != 0:
        return False
    return True
