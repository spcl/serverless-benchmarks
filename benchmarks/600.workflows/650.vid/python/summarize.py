import os
import io
import uuid
import json
import sys
from . import storage


def handler(event):
    frames = event["frames"]

    logs = {}
    for xs in frames:
      for key,value in xs.items():
        logs[key] = value

    return logs

