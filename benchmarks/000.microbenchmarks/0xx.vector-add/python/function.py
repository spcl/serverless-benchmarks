import datetime

import torch
import triton
import triton.language as tl


def get_device_and_sync(device_str: str):
    device = torch.device(device_str)
    if device.type == "cuda":
        sync = torch.cuda.synchronize
    elif device.type == "npu":
        sync = torch.npu.synchronize
    else:

        def sync():
            return None

    return device, sync


@triton.jit
def vector_add_kernel(x_ptr, y_ptr, out_ptr, n, BLOCK_SIZE: tl.constexpr):
    pid = tl.program_id(0)
    offsets = pid * BLOCK_SIZE + tl.arange(0, BLOCK_SIZE)
    mask = offsets < n
    x = tl.load(x_ptr + offsets, mask=mask)
    y = tl.load(y_ptr + offsets, mask=mask)
    tl.store(out_ptr + offsets, x + y, mask=mask)


def vector_add(num_elems, iters=100, device_str="cuda", x=None, y=None):

    device = torch.device(device_str)
    x = x.to(device)
    y = y.to(device)
    out = torch.empty_like(x)

    if device.type == "cuda":
        torch.cuda.synchronize()
    elif device.type == "npu":
        torch.npu.synchronize()

    for _ in range(iters):
        out = x + y

    if device.type == "cuda":
        torch.cuda.synchronize()
    elif device.type == "npu":
        torch.npu.synchronize()

    return out


def initialize(size, device_str="cuda"):
    device, sync = get_device_and_sync(device_str)
    x = torch.randn(size, device=device, dtype=torch.float32)
    y = torch.randn(size, device=device, dtype=torch.float32)
    return x, y


def _run_once(size, iters, device_str):

    generate_begin = datetime.datetime.now()
    array_1, array_2 = initialize(size, device_str=device_str)
    generate_end = datetime.datetime.now()

    process_begin = datetime.datetime.now()
    _ = vector_add(
        x=array_1,
        y=array_2,
        iters=iters,
        device_str=device_str,
        num_elems=size,
    )
    process_end = datetime.datetime.now()

    process_time = (process_end - process_begin) / datetime.timedelta(milliseconds=1)
    generate_time = (generate_end - generate_begin) / datetime.timedelta(milliseconds=1)
    avg_ms = process_time / iters

    bytes_per_iter = size * 3 * array_1.element_size()
    gbps = bytes_per_iter / (avg_ms / 1000.0) / 1e9

    return {
        "avg": f"{avg_ms:.4f} ms / iter",
        "effective BW": f"{gbps:.2f} GB/s",
        "measurement": {
            "compute_time": process_time,
            "generate_time": generate_time,
        },
    }


def handler(event):
    if "size" not in event:
        raise ValueError("event must contain 'size'")
    size = event["size"]
    iters = event.get("iters", 100)

    success = False
    error_msg = None
    device_used = "cpu"

    result = None

    if torch.cuda.is_available():
        try:
            result = _run_once(size, iters, device_str="cuda")
            success = True
            device_used = "cuda"
        except RuntimeError as e:

            msg = str(e)
            if (
                "no kernel image is available for execution on the device" in msg
                or "CUDA error" in msg
            ):
                # 回退到 CPU
                result = _run_once(size, iters, device_str="cpu")
                success = False
                device_used = "cpu"
                error_msg = (
                    "CUDA GPU not usable, computation was done on CPU. "
                    f"Original error: {msg}"
                )
            else:

                raise
    else:

        result = _run_once(size, iters, device_str="cpu")
        success = False
        device_used = "cpu"
        error_msg = "CUDA GPU not available, computation was done on CPU."

    result.update(
        {
            "device": device_used,
            "success": success,
            "error": error_msg,
        }
    )
    return result
