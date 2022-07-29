import os
from random import shuffle

size_generators = {
    'test' : (5, 10),
    'small': (20, 2**10),
    'large': (50, 2**10),
}

def buckets_count():
    return (1, 0)


def generate(size):
    elems = list(range(size))
    shuffle(elems)

    length = 0
    for i in elems:
        data = str(i % 255)
        length += len(data)
        if length > size:
            break
        yield data


def generate_input(data_dir, size, input_buckets, output_buckets, upload_func):
    count, size_bytes = size_generators[size]

    data_name = f"data-{size_bytes}.txt"
    data_path = os.path.join(data_dir, data_name)

    if not os.path.exists(data_path):
        with open(data_path, "w") as f:
            f.writelines(k for k in generate(size_bytes))

    upload_func(0, data_name, data_path)
    # os.remove(data_path)

    return { 'count': count, "bucket": input_buckets[0], "blob": data_name}