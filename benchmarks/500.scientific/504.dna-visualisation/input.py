import glob, os

def buckets_count():
    return (1, 1)

def generate_input(data_dir, size, input_buckets, output_buckets, upload_func):
    for file in glob.glob(os.path.join(data_dir, '*.fasta')):
        data = os.path.relpath(file, data_dir)
        upload_func(0, data, file)
    input_config = {'object': {}, 'bucket': {}}
    input_config['object']['key'] = data
    input_config['bucket']['input'] = input_buckets[0]
    input_config['bucket']['output'] = output_buckets[0]
    return input_config
