import glob, os

DATA_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'data')

def buckets_count():
    return (1, 1)

def generate_input(size, input_buckets, output_buckets, upload_func):
    cwd = os.getcwd()
    os.chdir(DATA_DIR)
    img = None
    for file in glob.glob("*.jpg"):
        img = file
        upload_func(0, file, os.path.join(DATA_DIR, file))
    os.chdir(cwd)
    #TODO: multiple datasets
    input_config = {'object': {}, 'bucket': {}}
    input_config['object']['key'] = img
    input_config['bucket']['input'] = input_buckets[0]
    input_config['bucket']['output'] = output_buckets[0]
    return input_config
