import datetime
import torch


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


def initialize(size, device_str="cuda"):
    device, _ = get_device_and_sync(device_str)
    pin = device.type == "cuda"
    host_tensor = torch.randn(size, device="cpu", dtype=torch.float32, pin_memory=pin)
    device_tensor = torch.empty(size, device=device, dtype=torch.float32)
    return host_tensor, device_tensor


def _run_once(size, iters, device_str):
    generate_begin = datetime.datetime.now()
    host_tensor, device_tensor = initialize(size, device_str=device_str)
    generate_end = datetime.datetime.now()

    device, sync = get_device_and_sync(device_str)

    sync()
    h2d_begin = datetime.datetime.now()
    for _ in range(iters):
        _ = host_tensor.to(device, non_blocking=True)
    sync()
    h2d_end = datetime.datetime.now()

    sync()
    d2h_begin = datetime.datetime.now()
    for _ in range(iters):
        _ = device_tensor.to("cpu", non_blocking=True)
    sync()
    d2h_end = datetime.datetime.now()

    generate_time = (generate_end - generate_begin) / datetime.timedelta(milliseconds=1)
    h2d_time = (h2d_end - h2d_begin) / datetime.timedelta(milliseconds=1)
    d2h_time = (d2h_end - d2h_begin) / datetime.timedelta(milliseconds=1)

    h2d_avg_ms = h2d_time / iters
    d2h_avg_ms = d2h_time / iters

    bytes_per_iter = size * host_tensor.element_size()

    h2d_gbps = bytes_per_iter / (h2d_avg_ms / 1000.0) / 1e9
    d2h_gbps = bytes_per_iter / (d2h_avg_ms / 1000.0) / 1e9

    return {
        "H2D_avg": f"{h2d_avg_ms:.4f} ms / iter",
        "H2D_effective_BW": f"{h2d_gbps:.2f} GB/s",
        "D2H_avg": f"{d2h_avg_ms:.4f} ms / iter",
        "D2H_effective_BW": f"{d2h_gbps:.2f} GB/s",
        "measurement": {
            "generate_time_ms": generate_time,
            "H2D_total_time_ms": h2d_time,
            "D2H_total_time_ms": d2h_time,
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
                result = _run_once(size, iters, device_str="cpu")
                success = False
                device_used = "cpu"
                error_msg = (
                    "CUDA GPU not usable, computation was done on CPU. " f"Original error: {msg}"
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
