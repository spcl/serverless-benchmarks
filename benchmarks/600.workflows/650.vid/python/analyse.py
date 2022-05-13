import os
import io
import uuid
import json
import sys
from . import storage

import cv2
import numpy as np

client = storage.storage.get_instance()


def load_labels(bucket, blob, dest_dir):
    path = os.path.join(dest_dir, "labels.txt")
    client.download(bucket, blob, path)

    with open(path, "r") as f:
        labels = [line.strip() for line in f.readlines()]

    return labels


def load_model(bucket, weights_blob, config_blob, dest_dir):
    weights_path = os.path.join(dest_dir, "model.weights")
    client.download(bucket, weights_blob, weights_path)

    config_path = os.path.join(dest_dir, "model.config")
    client.download(bucket, config_blob, config_path)

    net = cv2.dnn.readNet(weights_path, config_path)
    return net


def load_frames(bucket, blobs, dest_dir):
    for blob in blobs:
        path = os.path.join(dest_dir, blob)
        client.download(bucket, blob, path)
        yield cv2.imread(path)


def detect(net, img, labels):
    shape = (416, 416)
    height, width = shape
    img = cv2.resize(img, shape, interpolation=cv2.INTER_AREA)
    blob = cv2.dnn.blobFromImage(img, 1.0, shape, (0,0,0), True, crop=False)
    net.setInput(blob)

    layer_names = net.getLayerNames()
    output_layers = [layer_names[i-1] for i in net.getUnconnectedOutLayers()]

    outs = net.forward(output_layers)

    class_ids = []
    confidences = []
    boxes = []
    conf_threshold = 0.5
    nms_threshold = 0.4

    for out in outs:
        for detection in out:
            scores = detection[5:]
            class_id = np.argmax(scores)
            confidence = scores[class_id]
            if confidence > conf_threshold:
                center_x = int(detection[0] * width)
                center_y = int(detection[1] * height)
                w = int(detection[2] * width)
                h = int(detection[3] * height)
                x = center_x - w / 2
                y = center_y - h / 2
                class_ids.append(class_id)
                confidences.append(float(confidence))
                boxes.append([x, y, w, h])

    indices = cv2.dnn.NMSBoxes(boxes, confidences, conf_threshold, nms_threshold)

    return [{
        "class": labels[class_ids[idx]],
        "confidence": confidences[idx]
    } for idx in indices]


def handler(event):
    tmp_dir = "/tmp"

    frames = list(load_frames(event["frames_bucket"], event["frames"], tmp_dir))
    labels = load_labels(event["model_bucket"], event["model_labels"], tmp_dir)
    net = load_model(event["model_bucket"], event["model_weights"], event["model_config"], tmp_dir)

    preds = []
    for frame in frames:
        preds += detect(net, frame, labels)

    return preds

