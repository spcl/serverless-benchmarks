
import datetime, json, sys, traceback, csv

from utils import *
from tools import *

# imported function
from function import handler


cfg = json.load(open(sys.argv[1], 'r'))
repetitions = cfg['benchmark']['repetitions']
disable_gc = cfg['benchmark']['disable_gc']
input_data = cfg['input']

timedata = [0] * repetitions
try:
    start = start_benchmarking(disable_gc)
    for i in range(0, repetitions):
        begin = datetime.datetime.now()
        res = handler(input_data)
        stop = datetime.datetime.now()
        print(res, file = open(
                get_result_prefix(LOGS_DIR, 'output', 'txt'),
                'w'
            ))
        timedata[i] = [begin, stop]
    end = stop_benchmarking()
except Exception as e:
    print('Exception caught!')
    print(e)
    traceback.print_exc()


result = get_result_prefix(RESULTS_DIR, cfg['benchmark']['name'], 'csv')
with open(result, 'w') as f:
    csv_writer = csv.writer(f)
    csv_writer.writerow(['#Seconds from epoch.microseconds; Duration in microseconds'])
    csv_writer.writerow(['Begin','End','Duration'])
    for i in range(0, len(timedata)):
        csv_writer.writerow([
                timedata[i][0].strftime('%s.%f'),
                timedata[i][1].strftime('%s.%f'),
                (timedata[i][1] - timedata[i][0]) /
                    datetime.timedelta(microseconds=1)
            ])

experiment_data = {}
experiment_data['repetitions'] = repetitions
experiment_data['timestamps'] = process_timestamps(timedata)
experiment_data['start'] = str(start)
experiment_data['end'] = str(end)
print(json.dumps({'experiment': experiment_data, 'runtime': get_config()}, indent=2))
