import os
import io
import uuid
import json
import sys
from . import storage


def handler(list):
    logs = [det for dets in list for det in dets]
    logs = {f"frame{idx}": log for idx, log in enumerate(logs)}

    return logs

