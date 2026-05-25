size_generators = {
    "test" : (1, 100, 5),
    "small": (2, 500, 1024),
    "large": (3, 1000, 1024),
}

classifiers = [
    {"name": "SVC", "kernel": "linear", "C": 0.025},
    {"name": "RandomForestClassifier", "max_depth": 5, "n_estimators": 10},
    {"name": "RandomForestClassifier", "max_depth": 5, "n_estimators": 15},
    {"name": "AdaBoostClassifier"}
]

def buckets_count():
    return (0, 1)

def generate_input(data_dir, size, benchmarks_bucket, input_buckets, output_buckets, upload_func, nosql_func):
    n_classifiers, n_samples, n_features = size_generators[size]
    return {
        "classifiers": classifiers[:n_classifiers],
        "benchmark_bucket" : benchmarks_bucket,
        "dataset_bucket": output_buckets[0],
        "n_samples": n_samples,
        "n_features": n_features
    }
