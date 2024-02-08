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

def buckets_count():
    return (0, 0)

def generate_input(data_dir, size, input_buckets, output_buckets, upload_func):
    return { 'size': size_generators[size] }
