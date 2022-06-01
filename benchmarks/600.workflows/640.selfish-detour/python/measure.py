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
    res = (c_ulonglong*(2+num_samples))()
    ptr = cast(res, POINTER(c_ulonglong))
    lib.selfish_detour(num_samples, 900, ptr)

    tps = lib.get_ticks_per_second()

    res = list(res)
    payload = json.dumps({
        "res": res,
        "tps": tps
    })
    os.environ["SEBS_FUNCTION_RESULT"] = payload

    return payload

