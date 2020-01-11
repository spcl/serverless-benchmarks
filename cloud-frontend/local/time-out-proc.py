
import datetime, json, subprocess, sys, traceback, csv

from utils import *

cfg = json.load(open(sys.argv[1], 'r'))
repetitions = cfg['benchmark']['repetitions']
disable_gc = cfg['benchmark']['disable_gc']
input_data = cfg['input']
json.dump(input_data, open('input.json', 'w'))

timedata = [0] * repetitions
durations = [0] * repetitions
try:
    start = datetime.datetime.now()
    for i in range(0, repetitions):
        begin = datetime.datetime.now()
        out_file = '{}.txt'.format(get_result_prefix(LOGS_DIR, 'output', 'txt'))
        ret = subprocess.run(['/bin/bash', 'timeit.sh'],
            stdout=subprocess.PIPE)
        stop = datetime.datetime.now()
        timedata[i] = [begin, stop]
        durations[i] = int(ret.stdout.decode('utf-8'))
    end = datetime.datetime.now()
except Exception as e:
    print('Exception caught!')
    print(e)
    traceback.print_exc()


result = get_result_prefix(RESULTS_DIR, cfg['benchmark']['name'], 'csv')
with open('{}.csv'.format(result), 'w') as f:
    csv_writer = csv.writer(f)
    csv_writer.writerow(['#Seconds from epoch.microseconds; Duration in microseconds'])
    csv_writer.writerow(['Begin','End','Duration'])
    for i in range(0, len(timedata)):
        csv_writer.writerow([
                timedata[i][0].strftime('%s.%f'),
                timedata[i][1].strftime('%s.%f'),
                durations[i]
            ])

experiment_data = {}
experiment_data['repetitions'] = repetitions
experiment_data['timestamps'] = process_timestamps(timedata)
experiment_data['start'] = str(start)
experiment_data['end'] = str(end)
ret = subprocess.run(json.load(open('runners.json', 'r'))['config'], stdout=subprocess.PIPE)
config = json.loads(ret.stdout.decode('utf-8'))
print(json.dumps({'experiment': experiment_data, 'runtime': config}, indent=2))
