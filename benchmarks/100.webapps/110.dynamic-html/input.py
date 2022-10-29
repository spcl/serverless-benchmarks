
size_generators = {
    'test' : 10,
    'small' : 1000,
    'large': 100000
}

def buckets_count():
    return (0, 0)

def generate_input(data_dir, size, input_buckets, output_buckets, upload_func):
    input_config = {'username': 'testname'} 
    input_config['random_len'] = size_generators[size]
    return input_config
