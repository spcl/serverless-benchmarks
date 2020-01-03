
import datetime, json, sys, subprocess
cfg = json.load(open(sys.argv[1], 'r'))
ret = subprocess.run(['curl', '-X', 'POST',
    '{}/start'.format(cfg['benchmark']['mem']['analyzer_ip']),
    '-d',
    '{{"uuid": "{}" }}'.format(sys.argv[2])],
    stdout=subprocess.PIPE)
print(ret)


from utils import *
# imported function
from function import handler

repetitions = cfg['benchmark']['repetitions']
input_data = cfg['input']

timedata = [0] * repetitions
try:
    start = start_benchmarking(disable_gc)
    for i in range(0, repetitions):
        begin = datetime.datetime.now()
        res = handler(input_data)
        stop = datetime.datetime.now()
        print(res, file = open(
                '{}.txt'.format(get_result_prefix(LOGS_DIR, 'output', 'txt')),
                'w'
            ))
        timedata[i] = [begin, stop]
    end = stop_benchmarking()
except Exception as e:
    print('Exception caught!')
    print(e)
print('Done!')
while True:
    pass
subprocess.run(['curl', '-X', 'POST', '{}/stop'.format(cfg['benchmark']['mem']['analyzer_ip'])])

experiment_data = {}
experiment_data['repetitions'] = repetitions
experiment_data['timestamps'] = process_timestamps(timedata)
experiment_data['start'] = str(start)
experiment_data['end'] = str(end)
print(json.dumps({'experiment': experiment_data, 'runtime': get_config()}, indent=2))
