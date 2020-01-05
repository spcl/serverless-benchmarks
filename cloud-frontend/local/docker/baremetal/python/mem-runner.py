
import datetime, json, sys, subprocess
cfg = json.load(open(sys.argv[1], 'r'))
ret = subprocess.run(['curl', '-X', 'POST',
    '{}/start'.format(cfg['benchmark']['mem']['analyzer_ip']),
    '-d',
    '{{"uuid": "{}" }}'.format(sys.argv[2])],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE)
if ret.returncode != 0:
    import sys
    print('Mem analyzer initialization failed!')
    print(ret.stderr.decode('utf-8'))
    sys.exit()


from utils import *
# imported function
from function import handler

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
                '{}.txt'.format(get_result_prefix(LOGS_DIR, 'output', 'txt')),
                'w'
            ))
        timedata[i] = [begin, stop]
    end = stop_benchmarking()

    #while True:
    #    pass
    ret = subprocess.run(['curl', '-X', 'POST', '{}/stop'.format(cfg['benchmark']['mem']['analyzer_ip'])],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    experiment_data = {}
    experiment_data['repetitions'] = repetitions
    experiment_data['timestamps'] = process_timestamps(timedata)
    experiment_data['start'] = str(start)
    experiment_data['end'] = str(end)
    print(json.dumps({'experiment': experiment_data, 'runtime': get_config()}, indent=2))
except Exception as e:
    print('Exception caught!')
    print(e)
#print('Done!')
