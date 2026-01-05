import json
import random
import string

size_generators = {
    'test' : 10,
    'small' : 1000,
    'large': 50000
}

def buckets_count():
    return (1, 1)

def generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_func, nosql_func):
    data = []
    for _ in range(size_generators[size]):
        row = {}
        for i in range(1, 21):
            row[f'a{i}'] = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        data.append(row)
    with open('data.json', 'w') as f:
        json.dump(data, f, indent=4)
        filename = f.name
        
    upload_func(0, filename, filename)
        
    input_config = {'object': {}, 'bucket': {}}
    input_config['object']['key'] = filename
    input_config['bucket']['bucket'] = benchmarks_bucket
    input_config['bucket']['input'] = input_paths[0]
    input_config['bucket']['output'] = output_paths[0]

    return input_config