import os
import uuid
from . import storage

import sklearn.datasets as datasets
import numpy as np


def generate(n_samples, n_features):
    X, y = datasets.make_classification(
        n_samples,
        n_features,
        n_redundant=0,
        n_clusters_per_class=2,
        weights=[0.9, 0.1],
        flip_y=0.1,
        random_state=123
    )

    return X, y


def upload_dataset(benchmark_bucket, bucket, X, y):
    dataset_dir = os.path.join("/tmp", str(uuid.uuid4()))
    os.makedirs(dataset_dir, exist_ok=True)

    features_path = os.path.join(dataset_dir, "features.npy")
    labels_path = os.path.join(dataset_dir, "labels.npy")
    np.save(features_path, X)
    np.save(labels_path, y)

    client = storage.storage.get_instance()
    features = client.upload(benchmark_bucket, bucket + '/' + "features.npy", features_path)
    features = features.replace(bucket + '/', '')
    labels = client.upload(benchmark_bucket, bucket + '/' + "labels.npy", labels_path)
    labels = labels.replace(bucket + '/', '')

    return features, labels


def handler(event):
    classifiers = event["classifiers"]
    bucket = event["dataset_bucket"]
    benchmark_bucket = event["benchmark_bucket"]
    n_samples = int(event["n_samples"])
    n_features = int(event["n_features"])

    X, y = generate(n_samples, n_features)
    X_key, y_key = upload_dataset(benchmark_bucket, bucket, X, y)

    schedules = [{**c, "features": X_key, "labels": y_key, "bucket": bucket, "benchmark_bucket": benchmark_bucket} for c in classifiers]
    return {
        "schedules": schedules
    }
