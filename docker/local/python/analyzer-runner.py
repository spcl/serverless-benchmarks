
import datetime, json, sys, subprocess, os
ip_address = os.environ['DOCKER_HOST_IP']
cfg = json.load(open(sys.argv[1], 'r'))
ret = subprocess.run(['curl', '-X', 'POST',
    '{}:{}/start'.format(ip_address, cfg['benchmark']['analyzer']['analyzer_port']),
    '-d',
    '{{"uuid": "{}" }}'.format(sys.argv[2])],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE)
if ret.returncode != 0:
    import sys
    print('Analyzer initialization failed!')
    print(ret.stderr.decode('utf-8'))
    sys.exit(100)


from utils import *
from tools import *
# imported function
from function import function

repetitions = cfg['benchmark']['repetitions']
disable_gc = cfg['benchmark']['disable_gc']
input_data = cfg['input']

timedata = [0] * repetitions
try:
    start = start_benchmarking(disable_gc)
    for i in range(0, repetitions):
        begin = datetime.datetime.now()
        res = function.handler(input_data)
        stop = datetime.datetime.now()
        print(res, file = open(
                get_result_prefix(LOGS_DIR, 'output', 'txt'),
                'w'
            ))
        timedata[i] = [begin, stop]
    end = stop_benchmarking()

    ret = subprocess.run(
            [
                'curl', '-X', 'POST',
                '{}:{}/stop'.format(ip_address, cfg['benchmark']['analyzer']['analyzer_port']),
                '-d',
                '{{"uuid": "{}" }}'.format(sys.argv[2])
            ],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if ret.returncode != 0:
        import sys
        print('Analyzer deinitialization failed!')
        print(ret.stderr.decode('utf-8'))
        sys.exit(101)
    experiment_data = {}
    experiment_data['repetitions'] = repetitions
    experiment_data['timestamps'] = process_timestamps(timedata)
    experiment_data['start'] = str(start)
    experiment_data['end'] = str(end)
    print(json.dumps({'experiment': experiment_data, 'runtime': get_config()}, indent=2))
except Exception as e:
    print('Exception caught!')
    print(e)
    sys.exit(102)
sys.exit(0)
