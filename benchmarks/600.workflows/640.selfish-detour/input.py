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
