import glob
import os

def buckets_count():
    # one input bucket, one output bucket
    return (1, 1)

'''
    Generate test, small and large workload for the GPU video filter benchmark.

    :param data_dir: directory where benchmark data is placed
    :param size: workload size (e.g., "test", "small", "large")
    :param benchmarks_bucket: name of the benchmark bucket
    :param input_paths: list of input prefixes (one per input bucket)
    :param output_paths: list of output prefixes (one per output bucket)
    :param upload_func: upload function taking three params (bucket_idx, key, filepath)
    :param nosql_func: not used here
'''
def generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_func, nosql_func):
    last_key = None

    # Upload all .mp4 files from data_dir to bucket 0
    for file in glob.glob(os.path.join(data_dir, '*.mp4')):
        key = os.path.relpath(file, data_dir)
        upload_func(0, key, file)
        last_key = key

    if last_key is None:
        raise RuntimeError(f"No .mp4 files found in {data_dir}")

    input_config = {'object': {}, 'bucket': {}}

    # Use the last uploaded file as the input object
    input_config['object']['key'] = last_key
    input_config['object']['op'] = 'gpu-filter'     # must match your handler's operations dict
    input_config['object']['duration'] = 1          # seconds of video to process
    input_config['object']['num_iters'] = 10        # extra param for GPU workload intensity

    input_config['bucket']['bucket'] = benchmarks_bucket
    input_config['bucket']['input'] = input_paths[0]
    input_config['bucket']['output'] = output_paths[0]

    return input_config
