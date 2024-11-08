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
    input_config = {}
    input_config['charge_id'] = 'ch_1EeqlbF4aIiftV70qXHQewmn'
    input_config['customer_id'] = 'd749f277-0950-4ad6-ab04-98988721e475'
    input_config['outbound_flight_id'] = 'fae7c68d-2683-4968-87a2-dfe2a090c2d1'
    return input_config
