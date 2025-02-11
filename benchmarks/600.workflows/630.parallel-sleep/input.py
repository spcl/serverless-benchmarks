    #threads-duration
size_generators = {
    'test' : (2, 2),
    'small': (16, 20),
    'large': (50, 2),
    '2-1': (2, 1),
    '4-1': (4, 1),
    '8-1': (8, 1),
    '16-1': (16, 1),
    '2-5': (2, 5),
    '4-5': (4, 5),
    '8-5': (8, 5),
    '16-5': (16, 5),
    '2-10': (2, 10),
    '4-10': (4, 10),
    '8-10': (8, 10),
    '16-10': (16, 10),
    '2-15': (2, 15),
    '4-15': (4, 15),
    '8-15': (8, 15),
    '16-15': (16, 15),
    '2-20': (2, 20),
    '4-20': (4, 20),
    '8-20': (8, 20),
    '16-20': (16, 20),
    '50-1': (50, 1)
}

def buckets_count():
    return (0, 0)

def generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_func, nosql_func):
    count, sleep = size_generators[size]
    return { 'count': count, 'sleep': sleep }
