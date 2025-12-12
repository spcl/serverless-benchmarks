
import datetime, json, sys, traceback, csv, resource

from utils import *
from tools import *

# imported function
from function import function


cfg = json.load(open(sys.argv[1], 'r'))
repetitions = cfg['benchmark']['repetitions']
disable_gc = cfg['benchmark']['disable_gc']
input_data = cfg['input']

timedata = [0] * repetitions
os_times = [0] * repetitions
try:
    start = start_benchmarking(disable_gc)
    for i in range(0, repetitions):
        begin = datetime.datetime.now()
        begin_times = resource.getrusage(resource.RUSAGE_SELF)
        res = function.handler(input_data)
        end_times = resource.getrusage(resource.RUSAGE_SELF)
        stop = datetime.datetime.now()
        print(res, file = open(
                get_result_prefix(LOGS_DIR, 'output', 'txt'),
                'w'
            ))
        timedata[i] = [begin, stop]
        os_times[i] = [begin_times, end_times]
    end = stop_benchmarking()
except Exception as e:
    print('Exception caught!')
    print(e)
    traceback.print_exc()


result = get_result_prefix(RESULTS_DIR, cfg['benchmark']['name'], 'csv')
with open(result, 'w') as f:
    csv_writer = csv.writer(f)
    csv_writer.writerow(['#Seconds from epoch.microseconds; CPU times are in microseconds'])
    csv_writer.writerow(['Begin','End','Duration','User','Sys'])
    for i in range(0, len(timedata)):
        csv_writer.writerow([
                timedata[i][0].strftime('%s.%f'),
                timedata[i][1].strftime('%s.%f'),
                (timedata[i][1] - timedata[i][0]) /
                    datetime.timedelta(microseconds=1),
                (os_times[i][1].ru_utime - os_times[i][0].ru_utime) * 1e6,
                (os_times[i][1].ru_stime - os_times[i][0].ru_stime) * 1e6
            ])

experiment_data = {}
experiment_data['repetitions'] = repetitions
experiment_data['timestamps'] = process_timestamps(timedata)
experiment_data['start'] = str(start)
experiment_data['end'] = str(end)
print(json.dumps({'experiment': experiment_data, 'runtime': get_config()}, indent=2))
