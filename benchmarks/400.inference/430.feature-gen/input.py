import glob, os

def buckets_count():
    return (1, 0)

def upload_files(data_root, data_dir, upload_func):
    for root, dirs, files in os.walk(data_dir):
        prefix = os.path.relpath(root, data_root)
        for file in files:
            file_name = prefix + '/' + file
            filepath = os.path.join(root, file)
            upload_func(0, file_name, filepath)

def generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_func):
    dataset_name = 'reviews10mb.csv'
    upload_func(0, dataset_name, os.path.join(data_dir, 'dataset', dataset_name))

    input_config = {'object': {}, 'bucket': {}}
    input_config['object']['key'] = dataset_name
    input_config['bucket']['name'] = benchmarks_bucket
    input_config['bucket']['path'] = input_paths[0]
    input_config['extractors'] = 5
    return input_config
