# This function is not intended to be invoked directly. Instead it will be
# triggered by an HTTP starter function.
# Before running this sample, please:
# - create a Durable activity function (default name is "Hello")
# - create a Durable HTTP starter function
# - add azure-functions-durable to requirements.txt
# - run pip install -r requirements.txt

import logging
import json
import cv2
import numpy as np
import time
import azure.functions as func
import azure.durable_functions as df


def orchestrator_function(context: df.DurableOrchestrationContext):
    try:
        frames = 1
        res_split = yield context.call_activity('splitVideo',str(frames))
        frame_file_names = res_split.split()
        detectTemplate_res = []
        for file_name in frame_file_names:
            times  = yield context.call_activity('detectTemplate',file_name)
            detectTemplate_res.append(str(times))
        out_list= []
        out_list.extend(detectTemplate_res)
        return {'statusCode': 200,'time': int(round(time.time() * 1000)),'body': 'Got '+str(len(out_list)) + " frames back", 'events' : out_list}
    except Exception as e:
        return str(e)
    # splitVideoRet = yield context.call_activity('splitVideo', '2')
    # frames = splitVideoRet['frames']
    # times_split  = splitVideoRet['times']
    # out_times ={'split_time': times_split}
    # for i in range(len(frames)):
        # detectTemplateRet =  yield context.call_activity('detectTemplate','')
        # out_times['detectTemplateTime{}'.format(i)] = detectTemplateRet['times']    
    # return out_times
    # return 'nothing was done'

main = df.Orchestrator.create(orchestrator_function)