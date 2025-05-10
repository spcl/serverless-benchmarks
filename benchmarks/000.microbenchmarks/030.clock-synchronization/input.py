

def buckets_count():
    return 0, 1

def generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_func, nosql_func):
    return {
        'bucket': {
            'bucket': benchmarks_bucket,
            'output': output_paths[0],
        },
    }
