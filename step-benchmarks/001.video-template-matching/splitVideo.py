import json
import cv2
from urllib.request import urlopen
import numpy as np
import boto3
from urllib.parse import unquote_plus
import time

s3_client = boto3.client('s3')


def current_milli_time(): return int(round(time.time() * 1000))


path = "https://severless-test-aleqsio.s3.amazonaws.com/video.mp4"


def lambda_handler(event, context):
    times = {}
    times["global_start"] = current_milli_time()
    frame_count = 2 if "frame_count" not in event else event["frame_count"]

    video = cv2.VideoCapture(path)
    times["video_capture_end"] = current_milli_time()
    template = cv2.imdecode(np.asarray(
        bytearray(urlopen(templatePath).read()), dtype="uint8"), cv2.IMREAD_COLOR)
    frames = []
    s3 = boto3.resource("s3")
    while len(frames) < frame_count:
        ret, image = video.read()
        if not ret:
            break
        cv2.imwrite("/tmp/" + str(len(frames)) + ".png", image)
        s3.meta.client.upload_file("/tmp/" + str(len(frames)) + ".png",
                                   "severless-test-aleqsio", "frames/" + str(len(frames)) + ".png")
        frames.append("frames/" + str(len(frames)) + ".png")
    times["video_split_and_save_to_s3_end"] = current_milli_time()
    video.release()
    return {
        'statusCode': 200,
        'items': frames,
        'times': times
    }
