# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

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

VALID_CLASSIFIER_NAMES = ["SVC", "RandomForestClassifier", "AdaBoostClassifier"]

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

def validate_output(data_dir: str | None, input_config: dict, output: dict, language: str, storage = None) -> str | None:
    if output is None:
        return "Output is None"

    # Step Functions returns {"schedules": [...], "__request_id": "..."}
    if isinstance(output, dict):
        if "schedules" not in output:
            return f"Expected 'schedules' key in output dict, got keys: {list(output.keys())}"
        output = output["schedules"]

    if not isinstance(output, list):
        return f"Expected output to be a list, got {type(output).__name__}"

    input_classifiers = input_config["classifiers"]
    expected_count = len(input_classifiers)
    if len(output) != expected_count:
        return f"Expected {expected_count} results, got {len(output)}"

    # Build expected names in order from input
    expected_names = [c["name"] for c in input_classifiers]

    for i, entry in enumerate(output):
        if not isinstance(entry, dict):
            return f"Entry {i} is not a dict, got {type(entry).__name__}"

        if "name" not in entry:
            return f"Entry {i} is missing 'name' field"
        if "score" not in entry:
            return f"Entry {i} is missing 'score' field"

        name = entry["name"]
        score = entry["score"]

        if not isinstance(name, str):
            return f"Entry {i} 'name' is not a string, got {type(name).__name__}"

        if name not in VALID_CLASSIFIER_NAMES:
            return f"Entry {i} has invalid classifier name '{name}', expected one of {VALID_CLASSIFIER_NAMES}"

        # Output classifier name must match the corresponding input classifier
        if name != expected_names[i]:
            return f"Entry {i} classifier name '{name}' does not match input classifier '{expected_names[i]}'"

        if not isinstance(score, (int, float)):
            return f"Entry {i} 'score' is not a float, got {type(score).__name__}"

        if score < 0.0 or score > 1.0:
            return f"Entry {i} 'score' is {score}, expected value between 0.0 and 1.0"

    return None
