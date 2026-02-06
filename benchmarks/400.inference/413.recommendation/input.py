import os


def buckets_count():
    return (2, 0)


def upload_files(data_root, data_dir, upload_func):
    for root, _, files in os.walk(data_dir):
        prefix = os.path.relpath(root, data_root)
        for file in files:
            upload_func(0, os.path.join(prefix, file), os.path.join(root, file))


def generate_input(
    data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_func, nosql_func
):
    model_file = "dlrm_tiny.pt"
    upload_func(0, model_file, os.path.join(data_dir, "model", model_file))

    requests_file = "requests.jsonl"
    upload_func(1, requests_file, os.path.join(data_dir, "data", requests_file))

    cfg = {"object": {}, "bucket": {}}
    cfg["object"]["model"] = model_file
    cfg["object"]["requests"] = requests_file
    cfg["bucket"]["bucket"] = benchmarks_bucket
    cfg["bucket"]["model"] = input_paths[0]
    cfg["bucket"]["requests"] = input_paths[1]
    return cfg
