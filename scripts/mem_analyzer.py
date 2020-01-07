#!/usr/bin/env python3

import time, argparse, datetime, csv, json, subprocess, tempfile, os, operator, multiprocessing, threading
# We use multiprocessing since we need a background worker that is active 100% time
# Multithreading does not work since server never return to handle new requests
# Queue is used to communicate results
from multiprocessing import Process, Queue
from threading import Lock

# Bottle server
import waitress, bottle
from bottle import route, run, request

analyze = multiprocessing.Event()
all_instances_done = threading.Event()
lock = Lock()
data_queue = Queue()
out_file = None
measurement_data = []
number_of_apps = 0
finished_apps = []
measurement_directory = None
continuous_measurement_thread = None
samples_counter = 0

def measure(PID):
    global samples_counter, measurement_directory
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
        return False
    else:
        data_queue.put([
                timestamp.strftime('%s.%f'), 
                number_of_apps,
                int(ret.stdout.decode('utf-8').split('\n')[0])
            ])
        return True

def measure_now(PID):
    global finished_apps

    PIDs = finished_apps + [PID]
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
    measurement_data.append([
            timestamp.strftime('%s.%f'),
            len(PIDs),
            cached,
            *sums
        ])
    print('Process smem measurement in {}[s]'.format( (end-timestamp) / datetime.timedelta(seconds=1) ))

    # This is intended to be used only by one process at a time.
    # However, we add lock for extension just to be sure it's safe.
    # Further, modify collection at the end to make sure we don't signal too early.
    lock.acquire()
    finished_apps = PIDs
    lock.release()

    if len(PIDs) == number_of_apps + 1:
        all_instances_done.set() 
    all_instances_done.wait()

def get_pid(uuid):
    ret = subprocess.run('ps -fe | grep {}'.format(uuid), stdout=subprocess.PIPE, shell=True)
    PID = int(ret.stdout.decode('utf-8').split('\n')[0].split()[1])
    return PID

def measure_memory(PID):
    global samples_counter
    samples_counter = 0
    while analyze.is_set():
        i = 0
        while i < 5:
            if not measure(PID):
                print('Measurements terminated!')
                return
            i += 1
            samples_counter += 1
    # in case we didn't get a measurement yet because the app finished too quickly
    measure(PID)
    samples_counter += 1
    data_queue.put('END')

@route('/start', method='POST')
def start_analyzer():
    global measurement_directory, continuous_measurement_thread
    if number_of_apps == 1:
        measurement_directory = tempfile.TemporaryDirectory()
        req = json.loads(request.body.read().decode('utf-8'))
        uuid = req['uuid']
        analyze.set()
        handler = Process(target=measure_memory, args=(get_pid(uuid),))
        continuous_measurement_thread = handler
        handler.start()

@route('/stop', method='POST')
def stop_analyzer():
    global continuous_measurement_thread
    if number_of_apps == 1:
        analyze.clear()
        # wait for measurements to finish before ending
        continuous_measurement_thread.join()
    # measure impact of running 1, 2, 3, ... N apps
    else:
        req = json.loads(request.body.read().decode('utf-8'))
        pid = get_pid(req['uuid'])
        measure_now(pid)

@route('/processed_apps', method='POST')
def processed_apps():
    return json.dumps({'apps' : len(finished_apps)})

@route('/dump', method='POST')
def dump_data():

    # Background measurement launches a new process
    if number_of_apps == 1:
        data = []
        # make sure that we get everything
        for v in iter(data_queue.get, 'END'):
            data.append(v)
        samples_counter = len(data)
    else:
        data = measurement_data
        samples_counter = len(finished_apps)
    if measurement_directory is not None:
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

    with open(out_file, 'w') as f:
        csv_writer = csv.writer(f)
        csv_writer.writerow(['Timestamp', 'N', 'Cached', 'USS', 'PSS/SSS', 'RSS'])
        for val in data:
            csv_writer.writerow(val)
    if measurement_directory is not None:
        measurement_directory.cleanup()

parser = argparse.ArgumentParser(description='Measure memory usage of processes.')
parser.add_argument('port', type=int, help='Port run')
parser.add_argument('output', type=str, help='Output file.')
parser.add_argument('apps', type=int, help='Number of apps that is expected')
args = parser.parse_args()
port = int(args.port)
out_file = args.output
number_of_apps = int(args.apps)
app = bottle.default_app()
waitress.serve(app, host='localhost', port=port, threads=number_of_apps+1)
