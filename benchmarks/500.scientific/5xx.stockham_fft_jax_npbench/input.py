size_generators = {
    'test' : 10,
    'small' : 13,
    'large': 20
}

def generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_func, nosql_func):
    return { 'size': size_generators[size] }
 