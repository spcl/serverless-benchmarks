# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
import glob, os

def buckets_count():
    return (2, 0)

def upload_files(data_root, data_dir, upload_func):

    for root, dirs, files in os.walk(data_dir):
        prefix = os.path.relpath(root, data_root)
        for file in files:
            file_name = prefix + '/' + file
            filepath = os.path.join(root, file)
            upload_func(0, file_name, filepath)

'''
    Generate test, small and large workload for compression test.

    :param data_dir: directory where benchmark data is placed
    :param size: workload size
    :param input_buckets: input storage containers for this benchmark
    :param output_buckets:
    :param upload_func: upload function taking three params(bucket_idx, key, filepath)
'''

# Select a different input image for each size and record the expected
# ResNet50 classification outcome (idx and class label from ImageNet).
size_to_image_index = {
    'test': 0,
    'small': 1,
    'large': 2,
}

# Expected ResNet50 predictions for each image derived from val_map.txt
# and the imagenet_class_index.json bundled with the benchmark.
expected_results = {
    '800px-Porsche_991_silver_IAA.jpg': {'idx': 817, 'class': 'sports_car'},
    '512px-Cacatua_moluccensis_-Cincinnati_Zoo-8a.jpg': {'idx': 89, 'class': 'sulphur-crested_cockatoo'},
    '800px-Sardinian_Warbler.jpg': {'idx': 13, 'class': 'junco'},
}

def generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_func, nosql_func):

    # upload model
    model_name = 'resnet50-19c8e357.pth'
    upload_func(0, model_name, os.path.join(data_dir, 'model', model_name))
    model_name_cpp = 'resnet50.pt'
    upload_func(0, model_name_cpp, os.path.join(data_dir, 'model', model_name_cpp))

    input_images = []
    resnet_path = os.path.join(data_dir, 'fake-resnet')
    with open(os.path.join(resnet_path, 'val_map.txt'), 'r') as f:
        for line in f:
            img, img_class = line.split()
            input_images.append((img, img_class))
            upload_func(1, img, os.path.join(resnet_path, img))
    
    image_index = size_to_image_index.get(size, 0)
    selected_image = input_images[image_index][0]

    input_config = {'object': {}, 'bucket': {}}
    input_config['object']['model'] = model_name
    input_config['object']['input'] = selected_image
    input_config['object']['size'] = size
    input_config['bucket']['bucket'] = benchmarks_bucket
    input_config['bucket']['input'] = input_paths[1]
    input_config['bucket']['model'] = input_paths[0]
    return input_config

def validate_output(input_config: dict, output: dict) -> bool:
    result = output.get('result', {})
    cls = result.get('class', '')
    idx = result.get('idx', -1)
    if not (isinstance(cls, str) and len(cls) > 0 and isinstance(idx, int) and idx >= 0):
        return False
    image_key = input_config.get('object', {}).get('input', '')
    if image_key in expected_results:
        expected = expected_results[image_key]
        if idx != expected['idx']:
            return False
        if cls != expected['class']:
            return False
    return True
