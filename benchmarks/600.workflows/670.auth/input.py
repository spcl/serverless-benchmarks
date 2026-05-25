import random

size_generators = {
    "test" : 10,
    "small": 100,
    "large": 1000
}


def buckets_count():
    return (0, 0)


def generate_input(data_dir, size, input_buckets, output_buckets, upload_func):
    mult = size_generators[size]
    msg = "Who let the dogs out?\n" * mult

    return {
        "message": msg,
        "token": "allow"
    }