import os

size_generators = {
    "test" : (3, 10),
    "small": (10, 5),
    "large": (1000, 3),
}


def buckets_count():
    return (1, 1)


def generate_input(data_dir, size, input_buckets, output_buckets, upload_func):
    files = ["video.mp4", "frozen_inference_graph.pb", "faster_rcnn_resnet50_coco_2018_01_28.pbtxt"]
    for name in files:
        path = os.path.join(data_dir, name)
        upload_func(0, name, path)

    n_frames, batch_size = size_generators[size]
    return {
        "video": files[0],
        "n_frames": n_frames,
        "batch_size": batch_size,
        "frames_bucket": output_buckets[0],
        "input_bucket": input_buckets[0],
        "model_weights": files[1],
        "model_config": files[2]
    }