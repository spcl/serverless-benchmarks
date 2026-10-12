# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
import random
import os

size_generators = {
    "test" : (18, 6),
    "small": (30, 6),
    "large": (60, 6)
}


def buckets_count():
    return (1, 1)


def generate_input(data_dir, size, benchmarks_bucket, input_buckets, output_buckets, upload_func, nosql_func):
    num_frames, batch_size = size_generators[size]

    for bin in os.listdir(data_dir):
        path = os.path.join(data_dir, bin)
        if os.path.isfile(path):
            upload_func(0, bin, path)

    vid_dir = os.path.join(data_dir, "vid")
    vid_segs = sorted(os.listdir(vid_dir))
    new_vid_segs = []

    for i in range(num_frames):
        seg = vid_segs[i % len(vid_segs)]
        name = "{:08.0f}.y4m".format(i)
        path = os.path.join(vid_dir, seg)

        new_vid_segs.append(name)
        upload_func(0, name, path)

    assert(len(new_vid_segs) == num_frames)

    return {
        "segments": new_vid_segs,
        "benchmark_bucket": benchmarks_bucket,
        "input_bucket": input_buckets[0],
        "output_bucket": output_buckets[0],
        "batch_size": batch_size,
        "quality": 1
    }


def validate_output(data_dir: str | None, input_config: dict, output: dict, language: str, storage=None) -> str | None:
    if output is None:
        return "Output is None"

    # Output structure: {"segments": [list of batch dicts], "__request_id": "..."}
    # Each batch dict has: {"segments": [...y4m names...], "benchmark_bucket": "...", "output_bucket": "...", ...}
    if isinstance(output, dict):
        if "segments" not in output:
            return f"Expected 'segments' key in output, got keys: {list(output.keys())}"
        items = output["segments"]
        if not isinstance(items, list):
            return f"Expected 'segments' to be a list, got {type(items).__name__}"
    elif isinstance(output, list):
        items = output
    else:
        return f"Expected output to be a dict or list, got {type(output).__name__}"

    if len(items) == 0:
        return "Output 'segments' list is empty"

    for i, item in enumerate(items):
        if not isinstance(item, dict):
            return f"Segment batch {i} is not a dict, got {type(item).__name__}"

        if "benchmark_bucket" not in item:
            return f"Segment batch {i} missing 'benchmark_bucket'"
        if "output_bucket" not in item:
            return f"Segment batch {i} missing 'output_bucket'"
        if "segments" not in item:
            return f"Segment batch {i} missing 'segments'"

        segs = item["segments"]
        if not isinstance(segs, list) or len(segs) == 0:
            return f"Segment batch {i} 'segments' must be a non-empty list"

        if "quality" not in item:
            return f"Segment batch {i} missing 'quality'"
        if item["quality"] != input_config.get("quality"):
            return f"Segment batch {i} quality {item['quality']} != input quality {input_config.get('quality')}"

        for seg in segs:
            if not isinstance(seg, str) or not seg.endswith(".y4m"):
                return f"Segment batch {i} contains non-.y4m segment: {seg!r}"

    import math

    input_segs = input_config.get("segments", [])
    expected_segs = len(input_segs)

    # Every input segment must appear exactly once across all output batches
    if expected_segs > 0:
        output_segs = [seg for item in items for seg in item["segments"]]
        if len(output_segs) != expected_segs:
            return f"Total segments in output ({len(output_segs)}) != input segments ({expected_segs})"
        output_segs_set = set(output_segs)
        input_segs_set = set(input_segs)
        missing = input_segs_set - output_segs_set
        if missing:
            return f"Segments missing from output: {sorted(missing)}"
        extra = output_segs_set - input_segs_set
        if extra:
            return f"Unexpected segments in output: {sorted(extra)}"

    # Batch count should be ceil(n_segments / batch_size)
    batch_size = input_config.get("batch_size")
    if batch_size and expected_segs > 0:
        expected_batches = math.ceil(expected_segs / batch_size)
        if len(items) != expected_batches:
            return f"Expected {expected_batches} batches (ceil({expected_segs}/{batch_size})), got {len(items)}"

    return None
