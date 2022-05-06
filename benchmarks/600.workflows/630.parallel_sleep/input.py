size_generators = {
    'test' : (1000, 0),
    'small' : (50, 30),
    'large': (200, 60),
    'xlarge': (1000, 60)
}

def buckets_count():
    return (0, 0)

def generate_input(data_dir, size, input_buckets, output_buckets, upload_func):
    count, sleep = size_generators[size]
    return { 'count': count, 'sleep': sleep }