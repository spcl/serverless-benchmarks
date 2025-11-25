import os
import json
from typing import Tuple


def buckets_count() -> Tuple[int, int]:
    """
    One input bucket, one output bucket.
    """
    return (1, 1)


def generate_input(
    data_dir,
    size,
    benchmarks_bucket,
    input_paths,
    output_paths,
    upload_func,
    nosql_func,
):
    """
    Generate a JSON config for the warp-divergence microbenchmark
    and upload it to the input bucket.

    The JSON is what will be passed as `event` to function.handler().
    """
    if size == "test":
        num_warps = 512
        iters = 500
    elif size == "small":
        num_warps = 2048
        iters = 1000
    else:  # "large"
        num_warps = 8192
        iters = 2000

    active_lanes = [0, 4, 8, 16, 24, 32]

    config = {
        "num_warps": num_warps,
        "iters": iters,
        "active_lanes": active_lanes,
    }

    os.makedirs(data_dir, exist_ok=True)
    local_path = os.path.join(data_dir, f"warp_div_config_{size}.json")
    with open(local_path, "w") as f:
        json.dump(config, f)

    key = f"{input_paths[0].rstrip('/')}/warp_div_config_{size}.json"
    upload_func(0, key, local_path)

    # Return the config directly so runtimes that already have the payload
    # don't need to fetch it back from storage.
    return {"config": config}
