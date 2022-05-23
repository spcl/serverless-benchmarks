import os
import io
import uuid
import json
import sys
from . import storage


def handler(event):
    frames = event["frames"]
    logs = [det for dets in frames for det in dets]
    logs = {f"frame{idx}": log for idx, log in enumerate(logs)}

    return logs

