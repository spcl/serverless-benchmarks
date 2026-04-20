# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
import os

def buckets_count():
    return (2, 0)

def upload_files(data_root, data_dir, upload_func):

    for root, dirs, files in os.walk(data_dir):
        prefix = os.path.relpath(root, data_root)
        for file in files:
            file_name = prefix + '/' + file
            filepath = os.path.join(root, file)
            upload_func(0, file_name, filepath)

# Expected ResNet50 predictions for each image derived from val_map.txt
# and the imagenet_class_index.json bundled with the benchmark.
expected_results = {
    '800px-Porsche_991_silver_IAA.jpg': {'idx': 817, 'class': 'sports_car'},
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

    input_config = {'object': {}, 'bucket': {}}
    input_config['object']['model'] = model_name
    input_config['object']['input'] = input_images[0][0]
    input_config['object']['size'] = size
    input_config['bucket']['bucket'] = benchmarks_bucket
    input_config['bucket']['input'] = input_paths[1]
    input_config['bucket']['model'] = input_paths[0]
    return input_config

def validate_output(input_config: dict, output: dict, language: str, storage = None) -> str | None:

    image = input_config.get('object', {}).get('input', '')

    result = output.get('output', {})
    classification = result.get('class', '')
    idx = result.get('idx', -1)

    expected_idx = expected_results[image]['idx']
    expected_classification = expected_results[image]['class']

    if classification != expected_classification:
        return f"Classification is {classification}, but expected {expected_classification}"

    if idx != expected_idx:
        return f"Classification is {idx}, but expected {expected_idx}"

    return None
