import json
import os

def input_file(size):
    size_generators = {
        "test" : "Corvara_IT.tiff",
        "small": "Corvara_IT.tiff",
        "large": "Corvara_IT.tiff",
    }
    return size_generators[size]

def buckets_count():
    return (3, 3)

def sda_config():
    SDA_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "sda_config.json")
    with open(SDA_CONFIG_PATH, "r") as f:
        config = json.load(f)
    return config



def generate_input(data_dir, size, benchmarks_bucket,input_buckets, output_buckets, upload_func, nosql_func):
    INPUT_FILE = input_file(size)
    files = [INPUT_FILE]
    for file in files:
        upload_func(0, file, os.path.join(data_dir, file))
    return {
        "config_file": json.dumps(sda_config()),
        "input_file": INPUT_FILE,
        "input_bucket": input_buckets[0],
        "filter_output_bucket": output_buckets[0],
        "benchmark_bucket": benchmarks_bucket
    }