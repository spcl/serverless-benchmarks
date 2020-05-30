import json
import boto3
import cv2
import numpy as np
from urllib.request import urlopen
import time 
templatePath = "https://severless-test-aleqsio.s3.amazonaws.com/template.png"
current_milli_time = lambda: int(round(time.time() * 1000))
def lambda_handler(event, context):
    s3 = boto3.client("s3")
    times = {}
    times["detect_start"] = current_milli_time()
    template = cv2.imdecode(np.asarray(bytearray(urlopen(templatePath).read()), dtype="uint8"), cv2.IMREAD_COLOR)
    s3.download_file("severless-test-aleqsio", event, '/tmp/'+event.replace("frames/", ""))
    frame = cv2.imread('/tmp/'+event.replace("frames/", ""),1)
    res = cv2.matchTemplate(frame,template,cv2.TM_CCORR_NORMED)
    loc = cv2.minMaxLoc(res)
    times["detect_end"] = current_milli_time()
    return {
        'body': json.dumps(loc),
        'times': json.dumps(times)
    }
