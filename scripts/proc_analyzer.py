#!/usr/bin/env python3

import time, argparse, datetime, csv, json, subprocess, tempfile, os, operator, multiprocessing, threading

# Bottle server
import waitress, bottle
from bottle import route, run, request

def measure_memory_continuous(PID, samples_counter, measurement_directory):
    timestamp = datetime.datetime.now()
    ret = subprocess.run(
            ['''
                cp /proc/{}/smaps {}/smaps_{} && cat /proc/meminfo | grep ^Cached: | awk \'{{print $2}}\'
            '''.format(PID, measurement_directory.name, samples_counter)],
            stdout = subprocess.PIPE, stderr=subprocess.PIPE, shell = True
        )
    if ret.returncode != 0:
        print('Memory query failed!')
        print(ret.stderr.decode('utf-8'))
        return None
    else:
        return [
                timestamp.strftime('%s.%f'), 
                1,
                int(ret.stdout.decode('utf-8').split('\n')[0])
            ]

def postprocess_memory_continuous(data, measurement_directory):
    samples_counter = len(data)
    for i in range(0, samples_counter):
        ret = subprocess.run(
                ['''
                    awk \'/Shared/{{ sum += $2 }} /Private/{{ sum2 += 2 }} END {{ print sum2, sum }}\' {}/smaps_{}
                '''.format(measurement_directory.name, i)],
                stdout = subprocess.PIPE, shell = True
            )
        # remove newline and seperate into integers
        data[i].extend( map(int, ret.stdout.decode('utf-8').strip().split()) )
        rss = data[i][-1] + data[i][-2]
        data[i].append(rss)

def measure_memory_summary(PIDs, samples_counter=0, measurement_directory=None):

    pids_set = set(PIDs)
    timestamp = datetime.datetime.now()
    ret = subprocess.run(
            ['''
                cat /proc/meminfo | grep ^Cached: | awk '{print $2}' && smem -c 'pid uss pss rss'
            '''],
            stdout = subprocess.PIPE, shell = True
        )
    end = datetime.datetime.now()

    sums = [0]*3
    output = ret.stdout.decode('utf-8').split('\n')
    cached = int(output[0])
    count = 0
    # smem does not have an ability to filter by process IDs, only process command
    for line in output[2:]:
        if line:
            vals = list(map(int, line.split()))
            if vals[0] in pids_set:
                sums = list(map(operator.add, sums, vals[1:]))
                count +=1
    print('Process smem measurement in {}[s]'.format( (end-timestamp) / datetime.timedelta(seconds=1) ))
    return [
            timestamp.strftime('%s.%f'),
            len(PIDs),
            cached,
            *sums
        ]

def postprocess_memory_summary(data=None, measurement_directory=None):
    pass

measurers = {
    'memory': {
        'continuous' : {'measure': measure_memory_continuous, 'postprocess': postprocess_memory_continuous},
        'summary' : {'measure': measure_memory_summary, 'postprocess': postprocess_memory_summary}
    }
}

# We use multiprocessing since we need a background worker that is active 100% time
# Multithreading does not work since server function never returns to handle new requests
# Queue is used to communicate results
class continuous_measurement:
    data_queue = multiprocessing.Queue()
    analyze = multiprocessing.Event()
    measurement_directory = tempfile.TemporaryDirectory()
    measure_func = None
    postprocess_func = None
    handler = None

    def __init__(self, functions, number_of_apps=1):
        self.measure_func = functions['measure']
        self.postprocess_func = functions['postprocess']

    def measure(self, PID):
        samples_counter = 0
        while self.analyze.is_set():
            i = 0
            while i < 5:
                ret = self.measure_func(PID, samples_counter, self.measurement_directory)
                if ret is None:
                    print('Measurements terminated!')
                    return
                self.data_queue.put(ret)
                i += 1
                samples_counter += 1
        # in case we didn't get a measurement yet because the app finished too quickly
        self.measure_func(PID, samples_counter, self.measurement_directory)
        self.data_queue.put('END')

    def start(self, req):
        uuid = req['uuid']
        # notify the start of measurement
        self.analyze.set()
        self.handler = multiprocessing.Process(target=self.measure, args=(get_pid(uuid),))
        self.handler.start()

    def stop(self, req):
        # notify the end of measurement
        self.analyze.clear()
        # wait for measurements to finish before ending
        self.handler.join()
    
    def get_data(self):
        data = []
        # make sure that we get everything
        for v in iter(self.data_queue.get, 'END'):
            data.append(v)
        self.postprocess_func(data, self.measurement_directory)
        return data

    def cleanup(self):
        self.measurement_directory.cleanup()

    def processed_apps(self):
        return 0

# measure impact of running 1, 2, 3, ... N apps
class summary_measurement:
    all_instances_done = threading.Event()
    lock = threading.Lock()
    measurement_data = []
    number_of_apps = 0
    finished_apps = []
    measure_func = None
    postprocess_func = None

    def __init__(self, functions, number_of_apps):
        self.number_of_apps = number_of_apps
        self.measure_func = functions['measure']
        self.postprocess_func = functions['postprocess']

    def start(self, req):
        self.all_instances_done.clear()

    def stop(self, req):

        PID = get_pid(req['uuid'])
        PIDs = self.finished_apps + [PID]
        self.measurement_data.append(self.measure_func(PIDs))
        # This is intended to be used only by one process at a time.
        # However, we add lock for extension just to be sure it's safe.
        # Furthermore, modify collection after making measurements
        # Otherwise we might signal too early.
        self.lock.acquire()
        self.finished_apps = PIDs
        self.lock.release()

        if len(self.finished_apps) == self.number_of_apps:
            self.all_instances_done.set() 
        self.all_instances_done.wait()

    def get_data(self):
        return self.measurement_data

    def processed_apps(self):
        return len(self.finished_apps)
    
    def cleanup(self):
        pass

measurer = None
out_file = None

def get_pid(uuid):
    ret = subprocess.run('ps -fe | grep {}'.format(uuid), stdout=subprocess.PIPE, shell=True)
    PID = int(ret.stdout.decode('utf-8').split('\n')[0].split()[1])
    return PID

@route('/start', method='POST')
def start_analyzer():
    req = json.loads(request.body.read().decode('utf-8'))
    measurer.start(req)

@route('/stop', method='POST')
def stop_analyzer():
    req = json.loads(request.body.read().decode('utf-8'))
    measurer.stop(req)    

@route('/processed_apps', method='POST')
def processed_apps():
    return json.dumps({'apps' : measurer.processed_apps()})

@route('/dump', method='POST')
def dump_data():

    # Background measurement launches a new process
    data = measurer.get_data()
    samples_counter = len(data)

    with open(out_file, 'w') as f:
        csv_writer = csv.writer(f)
        csv_writer.writerow(['Timestamp', 'N', 'Cached', 'USS', 'PSS/SSS', 'RSS'])
        for val in data:
            csv_writer.writerow(val)

    measurer.cleanup()

parser = argparse.ArgumentParser(description='Measure memory usage of processes.')
parser.add_argument('port', type=int, help='Port run')
parser.add_argument('output', type=str, help='Output file.')
parser.add_argument('counter', type=str, choices=['memory', 'io'], help='Output file.')
parser.add_argument('apps', type=int, help='Number of apps that is expected')
args = parser.parse_args()
port = int(args.port)
out_file = args.output
number_of_apps = int(args.apps)
if number_of_apps == 1:
    measurer = continuous_measurement(measurers[args.counter]['continuous'], 1)
else:
    measurer = summary_measurement(measurers[args.counter]['summary'], number_of_apps)
app = bottle.default_app()
waitress.serve(app, host='localhost', port=port, threads=number_of_apps+1)
