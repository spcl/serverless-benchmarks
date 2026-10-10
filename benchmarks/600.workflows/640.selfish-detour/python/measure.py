import os
import json
from ctypes import *

def handler(event):
    num_samples = event["num_samples"]

    so_file = "selfish-detour.so"
    dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(dir, so_file)
    if not os.path.exists(path):
        path = os.path.join(dir, os.pardir, so_file)

    lib = cdll.LoadLibrary(path)
    lib.get_ticks_per_second.restype = c_double
    lib.selfish_detour.argtypes = [c_int, c_int, POINTER(c_ulonglong)]

    tps = lib.get_ticks_per_second()
    assert(tps > 0)

    res = (c_ulonglong*num_samples)()
    ptr = cast(res, POINTER(c_ulonglong))
    lib.selfish_detour(num_samples, 900, ptr)

    res = list(res)
    assert(all(x<=y for x, y in zip(res[2:], res[3:])))

    payload = json.dumps({
        "min_diff": res[0],
        "num_iterations": res[1],
        "timestamps": res[2:],
        "tps": tps
    })
    os.environ["SEBS_FUNCTION_RESULT"] = payload

    return "ok"

