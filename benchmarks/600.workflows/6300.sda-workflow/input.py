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
    return (1, 4)

def sda_config():
    SDA_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "sda-config.json")
    with open(SDA_CONFIG_PATH, "r") as f:
        config = json.load(f)
    return config


def generate_input(data_dir, size, benchmarks_bucket,input_buckets, output_buckets, upload_func, nosql_func):
    INPUT_FILE = input_file(size)
    upload_func(0, INPUT_FILE, os.path.join(data_dir, INPUT_FILE))
    CONFIG_FILE = "sda-config.json"
    upload_func(0, CONFIG_FILE, os.path.join(os.path.dirname(__file__), CONFIG_FILE))
    return {
        "config_file": CONFIG_FILE,
        "input_file": INPUT_FILE,
        "input_bucket": input_buckets[0],
        "filter_output_bucket": output_buckets[0],
        "cluster_output_bucket": output_buckets[1],
        "analysis_output_bucket": output_buckets[2],
        "final_output_bucket": output_buckets[3],
        "benchmark_bucket": benchmarks_bucket
    }