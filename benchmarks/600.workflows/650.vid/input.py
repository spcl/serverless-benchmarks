import os

size_generators = {
    "test" : (3, 10, "video_test.mp4"),
    "small": (10, 5, "video_small.mp4"),
    "large": (1000, 3, "video_large.mp4"),
}


def buckets_count():
    return (1, 1)


def generate_input(data_dir, size, input_buckets, output_buckets, upload_func):
    n_frames, batch_size, video_name = size_generators[size]
    files = ["frozen_inference_graph.pb", "faster_rcnn_resnet50_coco_2018_01_28.pbtxt", video_name]
    for name in files:
        path = os.path.join(data_dir, name)
        upload_func(0, name, path)

    return {
        "video": video_name,
        "n_frames": n_frames,
        "batch_size": batch_size,
        "frames_bucket": output_buckets[0],
        "input_bucket": input_buckets[0],
        "model_weights": files[0],
        "model_config": files[1]
    }
