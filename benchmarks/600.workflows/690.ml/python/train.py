import os
import uuid
import sys
from . import storage

from sklearn.model_selection import train_test_split
from sklearn.svm import SVC
from sklearn.ensemble import RandomForestClassifier, AdaBoostClassifier
from sklearn.preprocessing import StandardScaler
import numpy as np

def str_to_cls(cls_name):
    return getattr(sys.modules[__name__], cls_name)


def load_dataset(bucket, features, labels):
    dataset_dir = os.path.join("/tmp", str(uuid.uuid4()))
    os.makedirs(dataset_dir, exist_ok=True)

    features_path = os.path.join(dataset_dir, "features.npy")
    labels_path = os.path.join(dataset_dir, "labels.npy")

    client = storage.storage.get_instance()
    client.download(bucket, features, features_path)
    client.download(bucket, labels, labels_path)

    X = np.load(features_path)
    y = np.load(labels_path)

    return X, y


def preprocess(X, y):
    X = StandardScaler().fit_transform(X)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.4, random_state=123
    )

    return X_train, X_test, y_train, y_test


def train(clf, X, y):
    clf.fit(X, y)


def val(clf, X, y):
    return clf.score(X, y)


def handler(schedule):
    name = schedule.pop("name")
    X_key = schedule.pop("features")
    y_key = schedule.pop("labels")
    bucket = schedule.pop("bucket")

    clf = str_to_cls(name)(**schedule)

    X, y = load_dataset(bucket, X_key, y_key)
    X_train, X_test, y_train, y_test = preprocess(X, y)

    train(clf, X_train, y_train)
    score = val(clf, X_test, y_test)

    return {
        "name": name,
        "score": score
    }

