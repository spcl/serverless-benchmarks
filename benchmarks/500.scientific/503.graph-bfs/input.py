size_generators = {
    'test' : 10,
    'small' : 10000,
    'large': 100000
}

def buckets_count():
    return (0, 0)

def generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_func):
    return { 'size': size_generators[size] }
