import glob, os

def buckets_count():
    return (1, 0)

def generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_func):
    # Consider using a larger text file as input:
    # input_text_file = ''
    # upload_func(0, input_text_file, os.path.join(data_dir, 'input_text', input_text_file))

    input_config = {}
    input_config['mappers'] = 2
    input_config['text'] = 'the quick brown fox jumps jumps. over the lazy lazy lazy dog dog'
    return input_config
