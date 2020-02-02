size_generators = {
    'test' : 10,
    'small' : 10000,
    'large': 100000
}

def buckets_count():
    return (1, 1)

def generate_input(data_dir, size, input_buckets, output_buckets, upload_func):
    return { 'size': size_generators[size] }
