# This function is not intended to be invoked directly. Instead it will be
# triggered by an orchestrator function.
# Before running this sample, please:
# - create a Durable orchestration function
# - create a Durable HTTP starter function
# - add azure-functions-durable to requirements.txt
# - run pip install -r requirements.txt

import logging
import cv2
import time
import numpy as np
import tempfile
from os import listdir


def current_milli_time(): return int(round(time.time() * 1000))
# path = "https://severless-test-aleqsio.s3.amazonaws.com/video.mp4"
path = 'https://storageaccountbaserbb3d.blob.core.windows.net/test01/video.mp4'
def main(frameCount: str) -> str:
    out = ''
    try:
        times = {}
        times["global_start"] = current_milli_time()
        frame_count_ = 2 if int(frameCount) <= 0  else int(frameCount)
        frame_count_ = 2* frame_count_ 
        video = cv2.VideoCapture(path)
        times["video_capture_end"] = current_milli_time()
        frames = []
        i=0

        while len(frames) < frame_count_:
            i=i+1
            ret, image = video.read()
            if not ret:
                break
            file_name = '/tmp/'+ str(i)+'_'+str(time.time())
            with open(file_name,'wb') as fp:
                # fp = tempfile.NamedTemporaryFile()
                bytes  = image.tobytes()
                fp.write(bytes)
                # out += str(image.dtype) + ' ' + str(image.shape) + ' '
            # cv2.imwrite(fp.name,image)
            frames.append(file_name)
            frames.append(' ')
        times["video_split"] = current_milli_time()
        video.release()
        # return {'frames': frames,'times':times}
        out += ''.join(frames)
    except Exception as e:
        out += str(e)
    return out
