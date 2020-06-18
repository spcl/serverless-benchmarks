# This function is not intended to be invoked directly. Instead it will be
# triggered by an orchestrator function.
# Before running this sample, please:
# - create a Durable orchestration function
# - create a Durable HTTP starter function
# - add azure-functions-durable to requirements.txt
# - run pip install -r requirements.txt
import numpy as np
import logging
import time
import cv2
import json
from urllib.request import urlopen
# templatePath = "https://severless-test-aleqsio.s3.amazonaws.com/template.png"
templatePath ="https://storageaccountbaserbb3d.blob.core.windows.net/test01/template.png"
current_milli_time = lambda: int(round(time.time() * 1000))

def main(frames: str) -> dict:
    # frame = frames[0]
    times = {}
    out= None
    try:
        times["detect_start"] = current_milli_time()
        template = cv2.imdecode(np.asarray(bytearray(urlopen(templatePath).read()), dtype="uint8"), cv2.IMREAD_COLOR)
        # out = 'file_name : {} '.format(frames)
        frame = None
        with open(frames,'r+b') as f:
            data = f.read()
            frame = np.frombuffer(data,dtype='uint8')
            frame = np.reshape(frame,(1080, 1920, 3))
        res = cv2.matchTemplate(frame,template,cv2.TM_CCORR_NORMED)
        loc = cv2.minMaxLoc(res)
        times["detect_end"] = current_milli_time()
        # return {
        #     'locs': loc,
        #     'times': times
        # }
        out = {'body': json.dumps(loc),'times': json.dumps(times)}
    except Exception as e:
        out = {'ex' : str(e)}
    return out