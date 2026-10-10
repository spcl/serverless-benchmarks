# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

import os

size_generators = {
    "test" : (3, 10, "video_test.mp4"),
    "small": (10, 5, "video_small.mp4"),
    "large": (1000, 3, "video_large.mp4"),
}


def buckets_count():
    return (1, 1)


def generate_input(data_dir, size, benchmarks_bucket, input_buckets, output_buckets, upload_func, nosql_func):
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
        "benchmark_bucket": benchmarks_bucket,
        "input_bucket": input_buckets[0],
        "model_weights": files[0],
        "model_config": files[1]
    }


def validate_output(data_dir: str | None, input_config: dict, output: dict, language: str, storage=None) -> str | None:
    if output is None:
        return "Output is None"

    if not isinstance(output, dict):
        return f"Expected output to be a dict, got {type(output).__name__}"

    # __request_id is injected by the workflow engine, not a frame entry
    frame_entries = {k: v for k, v in output.items() if k != "__request_id"}
    if len(frame_entries) == 0:
        return "Output dict is empty, expected at least one frame entry"

    for frame_name, detections in frame_entries.items():
        if not isinstance(detections, list):
            return (
                f"Expected detections for frame '{frame_name}' to be a list, "
                f"got {type(detections).__name__}"
            )

        for i, detection in enumerate(detections):
            if not isinstance(detection, dict):
                return (
                    f"Detection {i} for frame '{frame_name}' is not a dict, "
                    f"got {type(detection).__name__}"
                )

            if "class" not in detection:
                return f"Detection {i} for frame '{frame_name}' is missing 'class' key"

            if not isinstance(detection["class"], str):
                return (
                    f"Detection {i} for frame '{frame_name}' has non-string 'class': "
                    f"{type(detection['class']).__name__}"
                )

            if "score" not in detection:
                return f"Detection {i} for frame '{frame_name}' is missing 'score' key"

            if not isinstance(detection["score"], (int, float)):
                return (
                    f"Detection {i} for frame '{frame_name}' has non-numeric 'score': "
                    f"{type(detection['score']).__name__}"
                )

            if not (0.0 <= detection["score"] <= 1.0):
                return (
                    f"Detection {i} for frame '{frame_name}' has score out of range "
                    f"[0, 1]: {detection['score']}"
                )

            # Handler filters detections at score > 0.5; any detection in output must pass this threshold
            if detection["score"] <= 0.5:
                return (
                    f"Detection {i} for frame '{frame_name}' has score {detection['score']:.4f} "
                    f"<= 0.5 (handler threshold)"
                )

    return None
