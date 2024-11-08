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
    dataset_name = 'reviews50mb.csv'
    upload_func(0, dataset_name, os.path.join(data_dir, 'dataset', dataset_name))

    model_name = 'lr_model.pk'
    # upload_func(0, model_name, os.path.join(data_dir, 'model', model_name))

    input_config = {'dataset': {}, 'model': {}, 'bucket': {}}
    input_config['dataset']['key'] = dataset_name
    input_config['model']['key'] = model_name
    input_config['bucket']['name'] = benchmarks_bucket
    input_config['bucket']['path'] = input_paths[0]
    input_config['input'] = 'The ambiance is magical. The food and service was nice! The lobster and cheese was to die for and our steaks were cooked perfectly.'
    return input_config
