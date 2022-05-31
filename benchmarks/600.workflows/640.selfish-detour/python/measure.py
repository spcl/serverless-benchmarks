import os
import json
from ctypes import *

def handler(event):
    num_samples = event["num_samples"]

    dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(dir, "selfish-detour.so")

    lib = cdll.LoadLibrary(path)
    res = (c_ulonglong*(2+num_samples))()
    ptr = cast(res, POINTER(c_ulonglong))
    lib.selfish_detour(num_samples, 900, ptr)
    res = list(res)

    os.environ["SEBS_FUNCTION_RESULT"] = json.dumps(res)

    return res

