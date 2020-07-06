from sebs.faas.function import Trigger

size_generators = {
    'test' : 1,
    'small' : 100,
    'large': 1000
}

def buckets_count():
    return (0, 0)

def generate_input(data_dir, size, input_buckets, output_buckets, upload_func, trigger_type):
    if trigger_type == Trigger.TriggerType.STORAGE:
        return {
            'file_path': '/home/milekj/sample.txt',
            'key': 'sample'
        }
    else:
        return { 'sleep': size_generators[size] }
