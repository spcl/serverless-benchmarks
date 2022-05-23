import random
import os

size_generators = {
    "test" : (18, 6),
    "small": (30, 6),
    "large": (60, 6)
}


def buckets_count():
    return (1, 1)


def generate_input(data_dir, size, input_buckets, output_buckets, upload_func):
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
        "input_bucket": input_buckets[0],
        "output_bucket": output_buckets[0],
        "batch_size": batch_size
    }