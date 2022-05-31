import os
import random

size_generators = {
    "test" : (50, 3),
    "small": (1000, 3),
    "large": (100000, 3)
}


def buckets_count():
    return (1, 1)


def generate_input(data_dir, size, input_buckets, output_buckets, upload_func):
    mult, n_mappers = size_generators[size]
    words = ["cat", "dog", "bird", "horse", "pig"]
    list = mult * words
    random.shuffle(list)

    list_path = os.path.join(data_dir, "list.txt")
    list_name = "words"
    with open(list_path, "w") as f:
        f.writelines(w+"\n" for w in list)
    upload_func(0, list_name, list_path)
    os.remove(list_path)

    return {
        "words_bucket": input_buckets[0],
        "words": list_name,
        "n_mappers": n_mappers,
        "output_bucket": output_buckets[0]
    }