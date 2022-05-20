import random
import os

size_generators = {
    "test" : (10, 6),
    "small": (100, 6),
    "large": (1000, 6)
}


def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def buckets_count():
    return (1, 1)


def generate_input(data_dir, size, input_buckets, output_buckets, upload_func):
    num_frames, batch_size = size_generators[size]

    for bin in os.listdir(data_dir):
        path = os.path.join(data_dir, bin)
        if os.path.isfile(path):
            upload_func(0, bin, path)

    vid_dir = os.path.join(data_dir, "vid")
    vid_segs = os.listdir(vid_dir)[:num_frames]
    for seg in vid_segs:
        path = os.path.join(vid_dir, seg)
        upload_func(0, seg, path)

    vid_segs = sorted(vid_segs)
    vid_segs = chunks(vid_segs, batch_size)

    return {
        "segments": [{
            "segments": segs,
            "input_bucket": input_buckets[0],
            "output_bucket": output_buckets[0],
        } for segs in vid_segs]
    }